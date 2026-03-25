# API base URLs
GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"
CLOB_API_BASE: str = "https://clob.polymarket.com"
OPEN_METEO_FORECAST_BASE: str = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ENSEMBLE_BASE: str = "https://ensemble-api.open-meteo.com/v1/ensemble"

# Market discovery
WEATHER_KEYWORDS: list = ["high temperature", "low temperature", "°C or higher", "°C or lower"]
MIN_LIQUIDITY_USD: float = 500.0
MAX_DAYS_TO_EXPIRY: int = 7

# Edge and sizing
EDGE_ALERT_THRESHOLD: float = 0.05       # 5% minimum edge to display as alert
MIN_KELLY_FRACTION: float = 0.01
MAX_KELLY_FRACTION: float = 0.25         # cap at 25% of bankroll
KELLY_FRACTIONAL_MULTIPLIER: float = 0.25  # quarter-Kelly to reduce variance

# Weather ensemble model
ENSEMBLE_MODEL: str = "ecmwf_ifs025"     # 51 members; alternative: "gfs025" (31 members)
FORECAST_TIMEZONE: str = "auto"          # resolves from lat/lon

# HTTP
REQUEST_TIMEOUT_SECONDS: int = 10
MAX_RETRIES: int = 3

# City coordinate lookup — extend as needed
CITY_COORDINATES: dict = {
    "Warsaw": (52.23, 21.01),
    "Berlin": (52.52, 13.41),
    "London": (51.51, -0.13),
    "Paris": (48.85, 2.35),
    "New York": (40.71, -74.01),
    "Chicago": (41.88, -87.63),
    "Los Angeles": (34.05, -118.24),
    "Tokyo": (35.69, 139.69),
    "Sydney": (-33.87, 151.21),
    "Madrid": (40.42, -3.70),
    "Rome": (41.90, 12.50),
    "Amsterdam": (52.37, 4.90),
    "Vienna": (48.21, 16.37),
    "Prague": (50.08, 14.44),
    "Budapest": (47.50, 19.04),
    "Stockholm": (59.33, 18.07),
    "Oslo": (59.91, 10.75),
    "Copenhagen": (55.68, 12.57),
    "Helsinki": (60.17, 24.93),
    "Zurich": (47.38, 8.54),
    "Brussels": (50.85, 4.35),
    "Lisbon": (38.72, -9.14),
    "Athens": (37.98, 23.73),
    "Istanbul": (41.01, 28.95),
    "Moscow": (55.75, 37.62),
    "Beijing": (39.91, 116.39),
    "Shanghai": (31.23, 121.47),
    "Seoul": (37.57, 126.98),
    "Singapore": (1.35, 103.82),
    "Mumbai": (19.08, 72.88),
    "Dubai": (25.20, 55.27),
    "São Paulo": (-23.55, -46.63),
    "Buenos Aires": (-34.60, -58.38),
    "Mexico City": (19.43, -99.13),
    "Toronto": (43.65, -79.38),
    "Vancouver": (49.25, -123.12),
    "Miami": (25.77, -80.19),
    "Houston": (29.76, -95.37),
    "Phoenix": (33.45, -112.07),
    "Seattle": (47.61, -122.33),
    "Denver": (39.74, -104.98),
    "Atlanta": (33.75, -84.39),
    "Boston": (42.36, -71.06),
    "Minneapolis": (44.98, -93.27),
    "Shenzhen": (22.54, 114.06),
    "Chongqing": (29.56, 106.55),
    "Guangzhou": (23.13, 113.26),
    "Hangzhou": (30.25, 120.15),
    "Nanjing": (32.06, 118.80),
    "Tianjin": (39.08, 117.20),
    "Xi'an": (34.27, 108.93),
    "Chengdu": (30.57, 104.07),
    "Wuhan": (30.59, 114.30),
    "Osaka": (34.69, 135.50),
    "Taipei": (25.05, 121.53),
    "Bangkok": (13.75, 100.52),
    "Jakarta": (-6.21, 106.85),
    "Kuala Lumpur": (3.14, 101.69),
    "Ho Chi Minh City": (10.82, 106.63),
    "Karachi": (24.86, 67.01),
    "Lagos": (6.45, 3.38),
    "Cairo": (30.06, 31.25),
    "Johannesburg": (-26.20, 28.04),
    "Nairobi": (-1.29, 36.82),
}
