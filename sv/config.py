"""Configuración de Stakevision. Todo lo ajustable está aquí."""
import os

# --- Reglas de selección -------------------------------------------------
ODDS_MIN = 1.65            # cuota mínima del pick final (simple o doble)
ODDS_MAX = 2.00            # cuota máxima del pick final
MIN_EDGE = 0.03            # valor mínimo: Betano debe pagar >= 3% sobre la cuota justa
MAX_EDGE = 0.20            # sobre 20% casi siempre es un error de datos: se descarta
LEG_ODDS_MIN = 1.20        # rango de cada selección dentro de una doble
LEG_ODDS_MAX = 1.60
MAX_REF_MARGIN = 0.08      # si el margen de Pinnacle en ese mercado supera 8%, la referencia no es confiable
MAX_CANDIDATES = 6         # candidatos que te llegan cada día para aprobar
MAX_STAKE = 5              # stake máximo (escala /10, ~% del bankroll)

# Ventana de partidos a analizar (horas desde ahora)
WINDOW_START_H = 1
WINDOW_END_H = 30

# --- Casas ---------------------------------------------------------------
BOOK = "betano"            # donde se apuesta
REFERENCE = "pinnacle"     # solo como regla de medir

# Mercados: solo partido completo (90'), sin props de jugadores, con 2 o 3 resultados.
# Hándicaps asiáticos de cuarto (x.25 / x.75) se excluyen porque se liquidan a medias.
ONLY_FULLTIME = True
# Tipos de mercado de OddsPapi que se analizan (por ahora solo goles; córners/tarjetas después).
ALLOWED_MARKET_TYPES = {"1x2", "totals", "bothteamsscore", "spreads", "drawnobet",
                        "teamtotals-team1", "teamtotals-team2", "toscore-team1", "toscore-team2"}

# Ligas: si la lista está vacía se analizan todas las que tengan cuotas de Betano y Pinnacle.
# Puedes limitarla con IDs de torneo de OddsPapi (ver data/tournaments.json).
TOURNAMENT_WHITELIST: list[int] = []
# Ligas preferidas (texto que aparece en "país + liga"). Tienen prioridad al elegir las 5 ligas
# del día, porque ahí la referencia de Pinnacle es más precisa. El resto se ordena por cantidad de partidos.
PRIORITY_LEAGUES = [
    "england premier league", "spain laliga", "italy serie a", "germany bundesliga", "france ligue 1",
    "uefa champions league", "uefa europa league", "conference league", "copa libertadores",
    "copa sudamericana", "chile primera", "brazil serie a", "argentina liga profesional",
    "netherlands eredivisie", "portugal primeira", "england championship", "usa mls", "mexico liga mx",
]
MAX_TOURNAMENTS_PER_CALL = 5     # límite de OddsPapi
ODDS_BATCHES = 1                 # grupos de 5 ligas por escaneo; cada grupo cuesta 2 consultas
# Con el plan gratis: 1 consulta de partidos + 2 por grupo = 3 consultas/día (~90 al mes).

# --- Horarios y zona -----------------------------------------------------
TIMEZONE = "America/Santiago"
RESULT_CHECK_AFTER_MIN = 135   # minutos tras el inicio para pedir el resultado

# --- Canales -------------------------------------------------------------
FREE_CHANNEL = "@stakevision"  # canal público

# --- Secretos (vienen de GitHub Secrets; nunca escribirlos aquí) -------------
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")
APIFOOTBALL_KEY = os.environ.get("APIFOOTBALL_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
STATE_KEY = os.environ.get("STATE_KEY", "")
LINK_CODE = os.environ.get("LINK_CODE", "")

# --- Rutas ---------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "data", "state.enc")
MARKETS_CACHE = os.path.join(ROOT, "data", "markets.json")
PUBLIC_HISTORY = os.path.join(ROOT, "docs", "historial.json")
