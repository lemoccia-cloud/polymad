"""Tests for WeatherClient — ensemble parsing (pure) and HTTP (mocked)."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.data.weather_client import WeatherClient, CityNotFoundError


def make_ensemble_response(n_members: int = 4, base_temp: float = 14.0) -> dict:
    """Build a fake Open-Meteo ensemble response for testing."""
    # 48 hours of data, two days
    times = [f"2026-03-24T{h:02d}:00" for h in range(24)] + \
            [f"2026-03-25T{h:02d}:00" for h in range(24)]
    members = {}
    for i in range(1, n_members + 1):
        # Slightly vary per member so we can test probability spread
        offset = (i - 1) * 0.5  # 0, 0.5, 1.0, 1.5 ...
        members[f"temperature_2m_member{i:02d}"] = [base_temp + offset - 1.0] * 48
    return {"hourly": {"time": times, **members}}


class TestComputeModelProbability:
    """Tests for _compute_model_probability (pure computation)."""

    def _client(self):
        return WeatherClient(session=MagicMock())

    def test_all_members_above_threshold(self):
        client = self._client()
        response = make_ensemble_response(n_members=4, base_temp=16.0)
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 13.0, "above")
        assert prob == pytest.approx(1.0)
        assert count == 4

    def test_no_members_above_threshold(self):
        client = self._client()
        response = make_ensemble_response(n_members=4, base_temp=10.0)
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 13.0, "above")
        assert prob == pytest.approx(0.0)
        assert count == 4

    def test_half_members_above_threshold(self):
        client = self._client()
        response2 = make_ensemble_response(n_members=4, base_temp=12.5)
        # base_temp=12.5, offset=[0,0.5,1.0,1.5] → temps=[11.5,12.0,12.5,13.0] daily max
        # Only member 4 (13.0) >= 13.0
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response2, resolution, 13.0, "above")
        assert prob == pytest.approx(0.25)  # 1 out of 4

    def test_direction_below(self):
        client = self._client()
        response = make_ensemble_response(n_members=4, base_temp=12.5)
        # temps = [11.5, 12.0, 12.5, 13.0] daily max
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 12.5, "below")
        # Members with max <= 12.5: member1 (11.5), member2 (12.0), member3 (12.5) = 3/4
        assert prob == pytest.approx(0.75)

    def test_direction_exact(self):
        client = self._client()
        # temps = [11.5, 12.0, 12.5, 13.0] daily max, threshold = 12
        # round(11.5)=12, round(12.0)=12, round(12.5)=12, round(13.0)=13
        # Members where round(max)==12: member1, member2, member3 = 3/4
        response = make_ensemble_response(n_members=4, base_temp=12.5)
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 12.0, "exact")
        assert prob == pytest.approx(0.75)

    def test_empty_hourly_returns_fallback(self):
        client = self._client()
        response = {"hourly": {"time": []}}
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 13.0, "above")
        assert prob == pytest.approx(0.5)  # fallback
        assert count == 0

    def test_date_not_in_forecast_returns_fallback(self):
        client = self._client()
        response = make_ensemble_response(base_temp=14.0)
        # Ask for a date that's not in the response
        resolution = datetime(2026, 4, 15, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 13.0, "above")
        assert prob == pytest.approx(0.5)
        assert count == 0

    def test_raw_temperatures_returned(self):
        client = self._client()
        response = make_ensemble_response(n_members=3, base_temp=15.0)
        resolution = datetime(2026, 3, 24, tzinfo=timezone.utc)
        prob, count, temps = client._compute_model_probability(response, resolution, 13.0, "above")
        assert len(temps) == 3
        assert all(isinstance(t, float) for t in temps)


class TestGetEnsembleForecast:
    def test_city_not_found_raises(self):
        client = WeatherClient(session=MagicMock())
        with pytest.raises(CityNotFoundError):
            client.get_ensemble_forecast(
                city="NonexistentCity",
                resolution_date=datetime(2026, 3, 24, tzinfo=timezone.utc),
                threshold_celsius=13.0,
                direction="above",
            )

    def test_returns_weather_forecast_object(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = make_ensemble_response(n_members=10, base_temp=15.0)
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        client = WeatherClient(session=mock_session)
        forecast = client.get_ensemble_forecast(
            city="Warsaw",
            resolution_date=datetime(2026, 3, 24, tzinfo=timezone.utc),
            threshold_celsius=13.0,
            direction="above",
        )
        assert forecast.city == "Warsaw"
        assert forecast.ensemble_member_count == 10
        assert 0.0 <= forecast.model_probability <= 1.0
        assert forecast.forecast_model == "ecmwf_ifs025"
