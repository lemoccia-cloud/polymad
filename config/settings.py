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
    # USA (additional)
    "Las Vegas": (36.17, -115.14),
    "San Francisco": (37.77, -122.42),
    "Philadelphia": (39.95, -75.16),
    "Dallas": (32.78, -96.80),
    "Portland": (45.52, -122.68),
    "Salt Lake City": (40.76, -111.89),
    "New Orleans": (29.95, -90.07),
    "Nashville": (36.17, -86.78),
    "Detroit": (42.33, -83.05),
    "Charlotte": (35.23, -80.84),
    "San Diego": (32.72, -117.16),
    "Sacramento": (38.58, -121.49),
    "Anchorage": (61.22, -149.90),
    "Honolulu": (21.31, -157.86),
    "Kansas City": (39.10, -94.58),
    "Tampa": (27.95, -82.46),
    "Orlando": (28.54, -81.38),
    "Pittsburgh": (40.44, -79.99),
    "Indianapolis": (39.77, -86.16),
    "Columbus": (39.96, -82.99),
    # Europe (additional)
    "Munich": (48.14, 11.58),
    "Milan": (45.46, 9.19),
    "Barcelona": (41.39, 2.15),
    "Lyon": (45.75, 4.84),
    "Hamburg": (53.55, 10.00),
    "Kyiv": (50.45, 30.52),
    "Bucharest": (44.43, 26.10),
    "Sofia": (42.70, 23.32),
    "Belgrade": (44.80, 20.46),
    "Riga": (56.95, 24.11),
    "Vilnius": (54.69, 25.28),
    "Tallinn": (59.44, 24.75),
    "Zagreb": (45.81, 15.98),
    "Sarajevo": (43.85, 18.36),
    "Thessaloniki": (40.64, 22.94),
    # Middle East & Asia (additional)
    "Riyadh": (24.69, 46.72),
    "Tel Aviv": (32.08, 34.78),
    "Doha": (25.29, 51.53),
    "Abu Dhabi": (24.47, 54.37),
    "Lahore": (31.55, 74.34),
    "Dhaka": (23.81, 90.41),
    "Colombo": (6.93, 79.85),
    "Yangon": (16.87, 96.19),
    "Kathmandu": (27.71, 85.31),
    "Almaty": (43.22, 76.85),
    "Tashkent": (41.30, 69.24),
    # Africa (additional)
    "Casablanca": (33.59, -7.62),
    "Accra": (5.56, -0.20),
    "Addis Ababa": (9.03, 38.74),
    "Dar es Salaam": (-6.79, 39.21),
    "Kinshasa": (-4.33, 15.32),
    # Americas (additional)
    "Lima": (-12.05, -77.04),
    "Bogota": (4.71, -74.07),
    "Santiago": (-33.45, -70.67),
    "Caracas": (10.48, -66.88),
    "Guadalajara": (20.66, -103.35),
    "Monterrey": (25.67, -100.31),
    "Montreal": (45.50, -73.57),
    "Calgary": (51.05, -114.07),
}
