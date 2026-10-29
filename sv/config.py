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
MANUAL_TOP = 3
PROTECTED_LINES = True      # totales: «más de 2» en vez de «más de 2.5» (con 2 exactos se devuelve) si existe a buena cuota
PROTECTED_MIN_ODDS = 1.60   # piso de cuota SOLO para esas líneas protegidas (el resto sigue en 1.65)               # /buscar devuelve el top 3
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
# Fotos: solo de este año en adelante (fecha de la foto en Commons). Sin foto de 2026, se usa el diseño con escudos.
PHOTO_MIN_YEAR = 2026
AUTO_SCAN_FALLBACK = True
DAILY_SCAN_AT = (0, 5)          # el escaneo del día sale a las 00:05 (hora Chile) y mira solo los partidos de ese día
# --- Pick gratis automático ---------------------------------------------------
AUTO_FREE = True                 # tras el escaneo diario, el bot elige solo el pick gratis y lo publica
AUTO_FREE_DELAY_MIN = 30         # minutos para cancelarlo o cambiarlo antes de que salga
AUTO_FREE_MIN_LEAD_MIN = 90      # el partido debe empezar al menos 90 min después de publicarlo
AUTO_FREE_MIN_EDGE = -0.02       # cuota disponible como mucho un 2 % por debajo de la justa
AUTO_FREE_VIP_TOO = True         # también sale en VIP (cuenta dentro de los 2-4 del día)
LIVE_LOCK_ALERTS = True          # aviso en vivo apenas un pick queda ganado («¡VERDE ASEGURADO!»)
LIVE_LOCK_SINCE = "2026-10-27T19:00:00Z"
IG_REELS = True                  # postpartidos y noticias: Reel (video) en Instagram en vez de imagen
AUTO_FREE_INSTAGRAM = True       # y en el feed de Instagram, si está conectado
AUTO_FREE_RECAP_DELAY_MIN = 20
DAILY_TOP = 3                    # 00:05: los 3 mejores picks de fútbol del día (de ahí sale el gratis)
DAILY_BUILDERS = True           # tras el escaneo diario: 1 Bet Builder de fútbol para revisar
NBA_OWNER_BEFORE_MIN = (60, 80)   # NBA: previa → pronóstico A/B → Bet Builder, entre 80 y 60 min antes
NBA_INJURY_RECHECK_MIN = (20, 35)  # segunda revisión de bajas: aviso solo si aparece una baja importante nueva
NBA_BUILDER_BEFORE_MIN = (25, 40)  # Bet Builder NBA: entre 40 y 25 minutos antes de cada partido
LIVE_BB = True                  # fútbol en vivo: líneas que se están cumpliendo al descanso
LIVE_BB_CHECKS_PER_DAY = 4      # consultas de cuotas en vivo por día (cada una ~3 llamadas a OddsPapi)
LIVE_BB_MIN_ODDS = 1.60         # solo avisar si la línea paga al menos esto   # el post partido se comparte solo 20 min después del resultado
# --- NBA ------------------------------------------------------------------
NBA_ENABLED = True
NBA_SPORT_ID = 11
NBA_TOURNAMENT = 132
NBA_MARKET_TYPES = {"moneyline", "spreads", "totals", "teamtotals-team1", "teamtotals-team2"}
NBA_PREGAME = True           # previa exclusiva en el VIP antes de cada pick NBA
NBA_PREGAME_MIN = 28         # cuántos minutos antes (sale entre 28 y 8 min antes del inicio)
NBA_DAILY_SCAN = False       # la NBA ya no va en el escaneo de las 00:05...
NBA_PREGAME_PICKS = True     # ...sino ~30 min antes de cada partido (pronóstico sugerido + Bet Builder)
NBA_PICKS_LOOKAHEAD_H = 4    # una consulta de cuotas cubre los partidos de las próximas 4 horas
NBA_DAILY_GAMES = 3          # partidos de NBA que te llegan en el escaneo diario (cada uno con opción A y B)
NBA_DIGEST_HOUR = 10         # resumen diario de la NBA (hora Chile), solo para ti
NBA_LIVE_ALERTS = True       # alertas privadas de posibles remontadas durante los partidos
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")   # redacción en español de las noticias (plan gratuito)
LLM_MODELS: list = []   # vacío = se usan los modelos que Google ofrece a la clave (primero Flash)

# --- Rutas ---------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "data", "state.enc")
MARKETS_CACHE = os.path.join(ROOT, "data", "markets.json")
PUBLIC_HISTORY = os.path.join(ROOT, "docs", "historial.json")
