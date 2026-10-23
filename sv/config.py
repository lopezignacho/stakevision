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
MIN_DAILY_CANDIDATES = 5   # (VIP 2-4 + 1 gratis) si hay menos picks con valor, se completan con cuotas cercanas a la justa
FALLBACK_MIN_EDGE = -0.02
LIVE_CANDIDATE_MIN = 20     # un candidato en vivo vence a los 20 min (las cuotas cambian rápido)
LIVE_MAX_MINUTE = 75        # en vivo: solo partidos que empezaron hace menos de 75 min
MANUAL_TOP = 3               # /buscar devuelve el top 3
MANUAL_SEARCHES_PER_DAY = 4  # tope diario de /buscar para cuidar la cuota de OddsPapi  # piso para esas propuestas: como máximo 2% bajo la cuota justa
MAX_STAKE = 8              # nunca 9 ni 10: ninguna apuesta es segura
# Stake con valor según el edge: (edge menor que, stake). 1 punto = 0,5% del bankroll.
STAKE_BY_EDGE = [(0.05, 5), (0.08, 6), (0.12, 7), (9.99, 8)]

# Ventana de partidos a analizar (horas desde ahora)
WINDOW_START_H = 1
WINDOW_END_H = int(os.environ.get("SCAN_HOURS") or 30)  # se puede ampliar al lanzar a mano (máx. 47)

# --- Casas ---------------------------------------------------------------
BOOK = "betano"            # donde se apuesta
REFERENCE = "pinnacle"     # solo como regla de medir

# Mercados: solo partido completo (90'), sin props de jugadores, con 2 o 3 resultados.
# Hándicaps asiáticos de cuarto (x.25 / x.75) se excluyen porque se liquidan a medias.
ONLY_FULLTIME = True
# Tipos de mercado de OddsPapi que se analizan (por ahora solo goles; córners/tarjetas después).
ALLOWED_MARKET_TYPES = {"1x2", "totals", "bothteamsscore", "spreads", "drawnobet",
                        "teamtotals-team1", "teamtotals-team2", "toscore-team1", "toscore-team2"}

# Ligas que se analizan (ID de torneo de OddsPapi -> nombre). Solo primera división y torneos
# internacionales importantes: nada de ascenso, amateur, juveniles, reservas ni femenino.
# El orden es la prioridad cuando hay más ligas con partidos que grupos disponibles.
TOURNAMENTS: dict[int, str] = {
    # Selecciones
    16: "Mundial", 24660: "Mundial", 20434: "Repechaje Mundial",
    295: "Eliminatorias CONMEBOL", 11: "Eliminatorias UEFA",
    133: "Copa América", 1: "Eurocopa", 27: "Clasificatorias Eurocopa",
    23755: "UEFA Nations League", 36497: "Finalissima",
    140: "Copa Oro CONCACAF", 27420: "CONCACAF Nations League",
    # Clubes internacionales
    7: "Champions League", 384: "Copa Libertadores", 679: "Europa League",
    480: "Copa Sudamericana", 34480: "Conference League", 490: "Recopa Sudamericana",
    357: "Mundial de Clubes", 44289: "Copa Intercontinental FIFA", 465: "Supercopa de Europa",
    498: "CONCACAF Champions Cup",
    # Europa: las 5 grandes
    17: "Inglaterra · Premier League", 8: "España · LaLiga", 23: "Italia · Serie A",
    35: "Alemania · Bundesliga", 34: "Francia · Ligue 1",
    # Sudamérica principal
    27665: "Chile · Primera División", 244: "Chile · Primera División",
    27518: "Chile · Primera División (Apertura)", 27520: "Chile · Primera División (Clausura)",
    325: "Brasil · Serie A", 155: "Argentina · Liga Profesional", 28538: "Argentina · Copa de la Liga",
    # Norteamérica
    27464: "México · Liga MX (Apertura)", 27466: "México · Liga MX (Clausura)", 242: "EE.UU. · MLS",
    # Europa: otras primeras divisiones
    238: "Portugal · Liga Portugal", 37: "Países Bajos · Eredivisie", 38: "Bélgica · Pro League",
    52: "Turquía · Süper Lig", 36: "Escocia · Premiership", 215: "Suiza · Super League",
    45: "Austria · Bundesliga", 185: "Grecia · Super League", 39: "Dinamarca · Superliga",
    # Sudamérica: otras primeras divisiones
    27070: "Colombia · Liga DIMAYOR", 241: "Colombia · Primera A", 27072: "Colombia · Primera A (Clausura)",
    278: "Uruguay · Primera División", 240: "Ecuador · LigaPro", 406: "Perú · Liga 1",
    27098: "Paraguay · División de Honor", 27100: "Paraguay · División de Honor (Clausura)",
    693: "Paraguay · Primera División", 33980: "Bolivia · División Profesional",
    27871: "Bolivia · División Profesional (Clausura)", 231: "Venezuela · Primera División",
}
MAX_TOURNAMENTS_PER_CALL = 5     # límite de OddsPapi
ODDS_BATCHES = 4                 # máximo de grupos de 5 ligas por escaneo (20 ligas); cada grupo = 2 consultas
# Solo se consultan las ligas con partidos en las próximas 30 h. Si un día hay más de 20,
# se toman las primeras según el orden de arriba (prioridad).

# --- Horarios y zona -----------------------------------------------------
TIMEZONE = "America/Santiago"
AUTO_SCAN_FALLBACK = True
# --- NBA ------------------------------------------------------------------
NBA_ENABLED = True
NBA_SPORT_ID = 11
NBA_TOURNAMENT = 132
NBA_MARKET_TYPES = {"moneyline", "spreads", "totals", "teamtotals-team1", "teamtotals-team2"}
NBA_DAILY_GAMES = 3          # partidos de NBA que te llegan en el escaneo diario (cada uno con opción A y B)
NBA_DIGEST_HOUR = 10         # resumen diario de la NBA (hora Chile), solo para ti
NBA_LIVE_ALERTS = True       # alertas privadas de posibles remontadas durante los partidos   # si el disparo de las 09:07 no corre, la revisión lanza el escaneo del día
REMINDER_BEFORE_MIN = 30      # aviso en los canales antes del partido
RESULT_CHECK_AFTER_MIN = 135   # minutos tras el inicio para buscar el marcador final
RESULT_RETRY_MIN = 20          # si el marcador aún no está, reintentar cada 20 min
RESULT_GIVE_UP_MIN = 360       # 6 h después del inicio sin marcador: te lo pregunta a ti

# --- Canales -------------------------------------------------------------
FREE_CHANNEL = "@stakevision"  # canal público
PUBLIC_SITE = "https://lopezignacho.github.io/stakevision"  # web pública (GitHub Pages)

# --- Secretos (vienen de GitHub Secrets; nunca escribirlos aquí) -------------
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")
APIFOOTBALL_KEY = os.environ.get("APIFOOTBALL_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
STATE_KEY = os.environ.get("STATE_KEY", "")
LINK_CODE = os.environ.get("LINK_CODE", "")
INSTAGRAM_TOKEN = os.environ.get("INSTAGRAM_TOKEN", "")

# --- Rutas ---------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "data", "state.enc")
MARKETS_CACHE = os.path.join(ROOT, "data", "markets.json")
PUBLIC_HISTORY = os.path.join(ROOT, "docs", "historial.json")
