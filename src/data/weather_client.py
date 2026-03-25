import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from config import settings
from src.models.market import WeatherForecast

logger = logging.getLogger(__name__)


class CityNotFoundError(Exception):
    pass


class WeatherAPIError(Exception):
    pass


class WeatherClient:
    """Fetches ensemble weather forecasts from Open-Meteo."""

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": "polyMad/1.0"})

    def get_ensemble_forecast(
        self,
        city: str,
        resolution_date: datetime,
        threshold_celsius: float,
        direction: str,
        model: str = settings.ENSEMBLE_MODEL,
    ) -> WeatherForecast:
        """
        Compute model probability for a temperature market using ensemble forecasts.

        Args:
            city: city name (must be in settings.CITY_COORDINATES)
            resolution_date: date of the temperature observation
            threshold_celsius: temperature threshold to evaluate
            direction: "above" (high temp >= threshold) or "below" (high temp <= threshold)
            model: ensemble model identifier

        Returns:
            WeatherForecast with model_probability as fraction of members meeting the condition.

        Raises:
            CityNotFoundError: if city not in settings.CITY_COORDINATES
            WeatherAPIError: on persistent API failure
        """
        coords = settings.CITY_COORDINATES.get(city)
        if coords is None:
            raise CityNotFoundError(
                f"City {city!r} not found. Add it to settings.CITY_COORDINATES."
            )

        lat, lon = coords
        raw_response = self._fetch_ensemble_data(lat, lon, resolution_date, model)
        probability, member_count, raw_temps = self._compute_model_probability(
            raw_response, resolution_date, threshold_celsius, direction
        )

        return WeatherForecast(
            city=city,
            resolution_date=resolution_date,
            threshold_celsius=threshold_celsius,
            direction=direction,
            model_probability=probability,
            ensemble_member_count=member_count,
            forecast_model=model,
            raw_temperatures=raw_temps,
        )

    def _fetch_ensemble_data(
        self,
        latitude: float,
        longitude: float,
        resolution_date: datetime,
        model: str,
    ) -> dict:
        """Fetch hourly ensemble temperature data from Open-Meteo."""
        today = datetime.now(tz=timezone.utc).date()
        target_date = resolution_date.date()
        forecast_days = max(1, (target_date - today).days + 2)  # +2 buffer

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "models": model,
            "hourly": "temperature_2m",
            "forecast_days": min(forecast_days, 16),  # Open-Meteo max is 16
            "timezone": settings.FORECAST_TIMEZONE,
        }

        return self._get_with_retry(settings.OPEN_METEO_ENSEMBLE_BASE, params)

    def _compute_model_probability(
        self,
        raw_response: dict,
        resolution_date: datetime,
        threshold_celsius: float,
        direction: str,
    ) -> tuple:
        """
        Compute the fraction of ensemble members satisfying the temperature condition.

        Returns:
            (probability, member_count, per_member_max_temps)
        """
        hourly = raw_response.get("hourly", {})
        time_list = hourly.get("time", [])

        if not time_list:
            logger.warning("Empty hourly time data from ensemble API")
            return 0.5, 0, []

        # Find all hourly indices for the resolution date
        date_str = resolution_date.strftime("%Y-%m-%d")
        indices = [i for i, t in enumerate(time_list) if t.startswith(date_str)]

        if not indices:
            logger.warning("No hourly data found for date %s", date_str)
            return 0.5, 0, []

        # Collect all ensemble member arrays
        member_pattern = re.compile(r"^temperature_2m_member\d+$")
        member_keys = [k for k in hourly if member_pattern.match(k)]

        if not member_keys:
            # Fallback: single deterministic forecast
            logger.debug("No ensemble members found, using deterministic temperature_2m")
            det_temps = hourly.get("temperature_2m", [])
            if det_temps:
                day_temps = [det_temps[i] for i in indices if i < len(det_temps) and det_temps[i] is not None]
                if day_temps:
                    daily_max = max(day_temps)
                    if direction == "above":
                        prob = 1.0 if daily_max >= threshold_celsius else 0.0
                    else:
                        prob = 1.0 if daily_max <= threshold_celsius else 0.0
                    return prob, 1, [daily_max]
            return 0.5, 0, []

        # For each member, compute daily max temperature
        member_max_temps = []
        for key in sorted(member_keys):
            temps = hourly[key]
            day_temps = [
                temps[i]
                for i in indices
                if i < len(temps) and temps[i] is not None
            ]
            if day_temps:
                member_max_temps.append(max(day_temps))

        if not member_max_temps:
            return 0.5, 0, []

        # Count members satisfying the condition
        # direction: "above" = max >= threshold
        #            "below" = max <= threshold
        #            "exact" = round(max) == int(threshold)  (e.g. 18.4°C rounds to 18°C)
        if direction == "above":
            satisfying = sum(1 for t in member_max_temps if t >= threshold_celsius)
        elif direction == "below":
            satisfying = sum(1 for t in member_max_temps if t <= threshold_celsius)
        else:  # "exact"
            target = int(round(threshold_celsius))
            satisfying = sum(1 for t in member_max_temps if int(round(t)) == target)

        probability = satisfying / len(member_max_temps)
        logger.debug(
            "%d/%d ensemble members satisfy %s %.1f°C (%s): probability=%.3f",
            satisfying, len(member_max_temps), direction, threshold_celsius,
            direction, probability,
        )

        return probability, len(member_max_temps), member_max_temps

    def get_deterministic_forecast(self, city: str, resolution_date: datetime) -> dict:
        """Fallback: single deterministic daily max temperature forecast."""
        coords = settings.CITY_COORDINATES.get(city)
        if coords is None:
            raise CityNotFoundError(f"City {city!r} not in CITY_COORDINATES")

        lat, lon = coords
        today = datetime.now(tz=timezone.utc).date()
        target_date = resolution_date.date()
        forecast_days = max(1, (target_date - today).days + 2)

        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max",
            "forecast_days": min(forecast_days, 16),
            "timezone": settings.FORECAST_TIMEZONE,
        }

        data = self._get_with_retry(settings.OPEN_METEO_FORECAST_BASE, params)
        daily = data.get("daily", {})
        date_str = resolution_date.strftime("%Y-%m-%d")

        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])

        for i, d in enumerate(dates):
            if d == date_str and i < len(max_temps):
                return {"date": d, "max_temp": max_temps[i]}

        return {"date": date_str, "max_temp": None}

    def _get_with_retry(self, url: str, params: dict) -> dict:
        """GET with exponential backoff. Raises WeatherAPIError on failure."""
        delay = 1.0
        for attempt in range(settings.MAX_RETRIES):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response else 0
                if status >= 500 and attempt < settings.MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise WeatherAPIError(f"HTTP {status} from {url}: {exc}") from exc
            except requests.exceptions.RequestException as exc:
                if attempt < settings.MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise WeatherAPIError(f"Request failed for {url}: {exc}") from exc

        raise WeatherAPIError(f"All {settings.MAX_RETRIES} retries exhausted for {url}")
