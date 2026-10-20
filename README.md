# Stakevision

Sistema automático de pronósticos de fútbol:

1. **Cada mañana (09:07 Chile)** busca partidos de las próximas 30 horas y compara cada cuota de **Betano** con la cuota justa de **Pinnacle** (sin su margen).
2. Se queda con picks de **valor ≥ 3%** y **cuota final entre 1.65 y 2.00**: simples primero; dobles solo si cada selección tiene valor por sí sola.
3. Te los manda por privado en Telegram. Con **🖼 Elegir** genera la imagen del pick y te deja publicarlo en **👑 VIP**, **👑🎁 VIP + Gratis** y/o **📸 Instagram** (los que tú decidas); o **❌ Descartar**.
4. Lo aprobado se publica solo en los canales (revisión cada 5 minutos, todo el día).
5. Cada pick sale a los canales con su imagen (logo, cupón con las selecciones e ícono del deporte) y 30 minutos antes del partido el bot avisa que está por comenzar.
6. Unas 2 h 15 min después del inicio, busca el marcador final (90') y **califica solo** el pick: ✅ verde, ❌ roja o ↩️ nula (devuelta). Lo publica como respuesta al pick y te avisa con un botón **✏️ Corregir** por si algo no cuadra. Si el marcador aún no está, reintenta cada 20 min; si a las 6 h no aparece, o el mercado no se puede leer, te pregunta a ti.
7. Los resultados verdes y nulos salen en los canales con imagen. Cuando un pick sale **verde**, el bot te manda por privado una imagen de celebración (formato Instagram) y el texto listo para copiar y publicar.
8. La web (`docs/`) muestra el historial y las cifras, calculadas automáticamente. Los picks VIP aparecen en la web recién cuando su partido termina y se cierra el resultado.

Todo corre gratis en GitHub Actions + GitHub Pages. El estado privado se guarda **cifrado** en `data/state.enc`.

## Puesta en marcha (una sola vez)

### 1. Secretos del repositorio
En GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Crea estos cinco:

| Nombre | Qué poner |
|---|---|
| `ODDSPAPI_KEY` | Tu API key de oddspapi.io (Account / Settings) |
| `APIFOOTBALL_KEY` | Tu API key de api-football (Dashboard) |
| `TELEGRAM_TOKEN` | El token de @StakevisionBot (en BotFather; idealmente uno nuevo con /revoke) |
| `STATE_KEY` | Una contraseña larga inventada por ti (cifra el estado; no la pierdas) |
| `LINK_CODE` | Una palabra secreta corta, por ejemplo `ojos-verdes-2026` |

Nunca pegues estas claves en el código ni en un chat.

### 2. Activar la web
**Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, carpeta `/docs`.

### 3. Preparar
**Actions → Preparar (una vez) → Run workflow**. Descarga la lista de mercados.

### 4. Vincular Telegram
- Escríbele a **@StakevisionBot** por privado: `/vincular TU_LINK_CODE`
- En el canal VIP publica: `/vincular_vip TU_LINK_CODE` (luego bórralo).
- En unos 10 minutos el bot confirma ambos.

### 5. Probar
**Actions → Escaneo diario → Run workflow** para lanzar un escaneo ahora mismo.

## Uso diario
- Revisa la cuota de cada candidato en tu app antes de aprobar.
- `/buscar` al bot: analiza en ese momento y te manda el top 3 (`/buscar 40` mira 40 horas adelante). Máximo 4 al día.
- `/compartir 8` al bot: te reenvía la imagen del pick #8 con los botones para VIP, Gratis o Instagram.
- Instagram: el bot responde solo los comentarios y mensajes directos típicos (precio, pick gratis, stake, resultados…) y te avisa por Telegram lo que no entiende o lo delicado (pagos, posibles menores, problemas con el juego). Textos en `sv/ig_inbox.py`.
- `/envivo` al bot: busca valor en partidos que se están jugando (el candidato vence a los 20 minutos).
- `/estado` al bot: candidatos pendientes, picks en juego, historial y consultas de OddsPapi usadas.
- `/ayuda`: lista de comandos.

## Ajustes
Todo en `sv/config.py`: rango de cuotas, valor mínimo, cantidad de candidatos, stake máximo y la lista `TOURNAMENTS` de ligas (IDs en `data/tournaments.json`).

## Límites del plan gratis
- OddsPapi: cada escaneo usa 1 consulta de partidos + 2 por cada grupo de 5 ligas con partidos ese día (entre 3 y 9 al día según cuántas ligas jueguen; tope de 20 ligas por escaneo). Los resultados no gastan OddsPapi.
- API-Football: el sistema usa como máximo 40 consultas por ejecución (el plan da 100 al día). Si no responde, el pick sale sin el contexto de forma reciente.

+18 · Juega con responsabilidad.
