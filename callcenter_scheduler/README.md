# Horarios CDC — Sistema de Gestión de Personal (Call Center)

*(Antes "Turnos KFC" — el sistema es el mismo, solo cambió el nombre visible en la app.)*


## Cómo correrlo en tu PC

1. Instala las dependencias (una sola vez):
   ```
   pip install -r requirements.txt --break-system-packages
   ```
   (si no usas Linux/`--break-system-packages`, simplemente: `pip install -r requirements.txt`)

2. Levanta el servidor:
   ```
   uvicorn main:app --reload
   ```

3. Abre en el navegador: **http://localhost:8000** — te va a pedir usuario y contraseña.

## Acceso (usuarios y contraseñas)

La primera vez que arranca el sistema, crea automáticamente 2 usuarios (verás sus
contraseñas en la consola donde corre `uvicorn`, solo esa primera vez):

| Usuario | Contraseña temporal | Rol |
|---|---|---|
| `admin` | `Admin2026*` | Admin (operación diaria) |
| `superadmin` | `SuperAdmin2026*` | Superadmin (todo + Tarifas + Usuarios) |

**Cambia estas contraseñas en tu primer ingreso** — el sistema te va a pedir hacerlo
automáticamente (modal obligatorio). También puedes cambiarla luego desde "Mi cuenta"
en el menú.

- **Admin**: acceso a Personal, Disponibilidad, Permisos, Métricas, Horarios, Brecha de
  Personal, Importar Datos — salvo que un superadmin le haya restringido módulos
  específicos (ver abajo).
- **Superadmin**: todo lo anterior + Tarifas (valores de nómina) + Usuarios (crear/desactivar
  accesos) + **Auditoría** (registro de quién hizo qué acción sensible y cuándo: logins,
  cambios de tarifas, creación/eliminación de usuarios, borrado de llamadas) + **Configuración
  General**. Solo un superadmin puede crear otros usuarios o ver el registro de auditoría.

**Permisos por módulo (solo superadmin puede configurarlos)**: al crear un usuario `admin`,
puedes elegir "Acceso a todos los módulos" (comportamiento de siempre) o desmarcarlo y
elegir exactamente cuáles — Inicio, Importar Datos, Personal, Disponibilidad, Permisos,
Métricas, Turnos, Horarios, Historial, Comparar, Brecha de Personal. Esto **no es solo
cosmético**: el servidor rechaza con error 403 cualquier intento de acceder a datos de un
módulo no permitido, aunque alguien intente llamar la API directamente sin pasar por el
menú. Tarifas/Usuarios/Auditoría/Configuración General quedan siempre exclusivos de
superadmin, sin importar lo que se marque. Los módulos de un usuario ya creado se editan
desde la pestaña Usuarios → botón "Módulos" en su fila.

Esta tabla también está visible dentro de la app: pestaña **Usuarios → "Qué puede hacer
cada rol"** — así cualquiera con acceso a esa pestaña puede consultarla sin abrir este README.

Las sesiones duran 12 horas. El archivo `.secret_key` (se genera solo la primera vez) firma
las sesiones — si lo borras, todos quedan desconectados y deben volver a ingresar.

4. Ve a la pestaña **"Importar Datos"** y sube ahí tus dos archivos Excel (disponibilidad
   y llamadas) — ya no hace falta usar la consola para esto.

   ⚠️ **Importante**: la base de datos (`callcenter.db`) NO viene dentro de este zip a
   propósito (para no pisar tu información real con datos de prueba). Esto significa que
   **cada vez que descomprimas una versión nueva del proyecto en una carpeta distinta,
   empieza vacía** y hay que volver a importar los Excel desde "Importar Datos". Si quieres
   conservar tu base de datos entre versiones, copia el archivo `callcenter.db` de la
   carpeta vieja a la nueva antes de arrancar el servidor.

## Qué hay en cada vista

- **Inicio**: pantalla de aterrizaje al ingresar — resumen de personal (activos, Full
  Time/Part Time, alertas de disponibilidad por revisar), modo de horarios activo
  (📋 Plantillas / 🔓 Libre), próximo festivo, métricas generales del último dato cargado
  (% contestación, TMO, llamadas), brecha de personal si aplica, y accesos rápidos a los
  módulos más usados (Generar horario, Métricas, Brecha, Turnos, Importar).
- **Importar Datos**: sube tu Excel de disponibilidad y tu Excel de llamadas directamente
  desde el navegador. Te dice cuántos registros se crearon/actualizaron y si algo faltó
  (cédulas, disponibilidad sin información, etc.). Es seguro repetir la carga de llamadas
  cada semana: las duplicadas se detectan solas y no se cuentan dos veces.
- **Personal**: lista de asesores, sus horas mín/máx diarias y semanales, y una alerta
  automática ("Revisar") si la disponibilidad cargada no alcanza para cumplir su contrato.
  Botón "+ Nuevo asesor" para dar de alta gente nueva. Agrupados por **tipo de contrato**
  (Full Time / Part Time), como en la hoja de horarios que ya manejas.
  **Horas extra**: botón "Gestionar" en cada fila para autorizar horas extra puntuales a un
  asesor. Sin importar quién esté haciendo el cambio (admin o superadmin), el sistema
  **siempre exige las credenciales de un superadmin escritas en ese momento** — no basta con
  que la sesión ya sea de superadmin. Cada autorización queda en un registro propio (quién
  la pidió, quién la autorizó, cuántas horas, cuándo) y también en Auditoría. Una vez
  autorizadas, el generador de Horarios las usa automáticamente para esa persona cuando
  hace falta cubrir una brecha, sin tocar su contrato base guardado.
- **Disponibilidad**: selecciona un asesor y edita día por día — Completa / Rango horario /
  No disponible / Sin información. Se guarda al instante por día. El selector de asesor
  también está agrupado por Full Time / Part Time.
- **Permisos**: registra vacaciones, capacitación, incapacidades, etc. El sistema bloquea
  automáticamente si intentas crear un permiso que se solapa con uno ya existente para
  ese mismo asesor.
- **Métricas**: KPIs generales del histórico de llamadas (% contestadas, TMO, abandono),
  tendencia diaria, distribución de llamadas por hora del día, y el desglose franja horaria
  × día ahora muestra también cuántos **asesores necesitarías** en cada celda (Erlang C).
  Nueva tabla de **rendimiento por asesor** (llamadas contestadas, TMO, tiempo total en
  llamada, promedio por día activo) para el rango de fechas que filtres.
- **Turnos**: define los horarios válidos que tu operación permite (ej. "11:00-19:00",
  "17:00-21:00"), cada uno con los días de la semana en que aplica y, opcionalmente, una
  **hora de almuerzo** (ej. "1h de almuerzo" en un turno de 12:00-21:00 → 8h efectivas
  pagadas, no 9h). El sistema ubica automáticamente el almuerzo con 3 reglas: (1) nunca en
  la primera ni en la última hora del turno (siempre al menos 1h trabajada antes y después),
  (2) preferentemente dentro de la **ventana valle configurable** (por defecto 2:30pm-6pm,
  ajustable en Configuración General → `almuerzo_valle_inicio`/`almuerzo_valle_fin` — si el
  turno no alcanza a tocar esa ventana, ej. un turno solo de mañana, se relaja a cualquier
  hora del turno que respete la regla 1), y (3) reparte los almuerzos entre horas distintas
  del día — penaliza fuerte repetir una hora donde ya hay gente almorzando, para que no se
  amontonen todos a la vez dejando el teléfono sin nadie. Esa hora ni se paga ni cuenta como
  cobertura real — se refleja así en el cuadrante, el PDF, el Excel y en `costos.py`.
  **El sistema ya viene con 13 plantillas precargadas** (se crean solas la primera vez que
  arrancas, igual que los usuarios) — puedes editarlas o borrarlas desde esta pestaña.
  Ojo: la siembra automática **solo actúa si la tabla está vacía** — si ya tenías
  plantillas de una versión anterior (ej. sin la información de almuerzo), no se
  reemplazan solas. Usa el botón **"↺ Restaurar por defecto"** para forzar el set actual
  en cualquier momento (borra las que haya y deja las 13 estándar) — disponible para
  admin y superadmin, ya que Turnos es un módulo operativo del día a día.
  Si defines al menos una plantilla activa, el generador de Horarios **solo** arma turnos
  usando esos bloques exactos — no inventa horarios nuevos. Si borras todas, vuelve a
  funcionar en "modo libre" (turnos de duración variable ajustados a la demanda). La vista
  de Horarios muestra un indicador (📋 Modo Plantillas / 🔓 Modo Libre) para que siempre
  sepas cuál está aplicando.
- **Horarios**: elige el lunes de la semana, la meta de nivel de servicio, y una
  **proyección de actividad** (+5%/+10%/+20%/+30% para promos o campañas) que escala la
  demanda esperada antes de calcular personal.

  **Base de demanda** — de dónde sale el pronóstico de cuántas llamadas esperar cada hora:
  - **Automático (recomendado)**: usa TODO el histórico cargado, pero pesa más las semanas
    recientes (decaimiento exponencial: la última semana pesa 100%, la anterior 70%, la
    anterior a esa 49%, y así sucesivamente — factor ajustable en
    `_demanda_por_dia(..., factor_decaimiento=0.7)`).
  - **Semana(s) específica(s)**: eliges una o varias semanas puntuales (con checkboxes que
    muestran su rango de fechas y volumen de llamadas) y el pronóstico se calcula SOLO con
    esas, todas con el mismo peso — ignora el resto del histórico. Útil para excluir
    semanas atípicas (paros, errores de datos, promociones puntuales que no se van a
    repetir) o para basarte deliberadamente en una semana que consideras representativa.
    Si eliges varias, se promedian entre ellas.

  Genera el cuadrante completo con el **%
  de contestación estimado** (real, con la gente efectivamente programada), el costo
  total, el desglose (recargo nocturno, dominical, transporte) y las alertas de horas sin
  cubrir. El algoritmo corre en **2 pasadas**: primero reserva un **piso mínimo** (por
  defecto 50% del requerido) en TODOS los días, empezando por los más tranquilos —esto
  evita que un día de baja demanda (ej. Miércoles) quede casi huérfano porque la gente
  disponible ese día ya agotó su tope semanal de horas trabajando en los días de más
  prioridad, que se procesarían antes—. Luego, con el presupuesto que sobra, termina de
  cubrir en **orden de mayor a menor demanda real** (ej. Domingo antes que Miércoles), así
  el día que más le cuesta al negocio si queda mal cubierto se lleva primero lo que queda.
  Una pasada final de reparación garantiza que ningún día quede sin gente. Cada turno se
  ajusta al ancho real del pico de demanda en vez de siempre usar el máximo permitido.
  El piso mínimo es ajustable en Configuración General (`fraccion_piso_minimo`) — 0.50 dio
  el mejor equilibrio en pruebas (comparamos 0.30/0.40/0.50/0.60): mayor % de contestación
  total Y la menor diferencia entre el mejor y el peor día de la semana.

  **Penalización de desperdicio al elegir plantilla**: cuando varias plantillas de turno
  aplican a un mismo día (ej. Sábado tiene 9 de las 13 disponibles — el máximo), el
  algoritmo no solo mira cuántas horas de déficit cubre cada una, también penaliza cuántas
  de sus horas YA estaban completas — sin esto, con muchas plantillas superpuestas, el
  sistema no distinguía entre una plantilla ajustada y una ancha que sobre-cubre horas que
  no lo necesitaban. En pruebas, esto bajó el exceso de cobertura de Sábado en un ~33% sin
  afectar el resto de la semana.

  **Pase de rebalanceo entre días**: al final, el sistema busca gente que trabaja tanto un
  día con horas sobrantes como uno con déficit, y prueba cambiarles la plantilla de ambos
  días (sin agregar turnos nuevos ni tocar días de descanso) para que las horas que sobran
  en un día ayuden al otro. Cada cambio se valida con el cálculo real de Erlang C de los 2
  días afectados — si empeora cualquiera de los dos, se revierte solo ese cambio puntual
  (no todo el pase), así que lo que sí quedó aplicado nunca es peor que sin el rebalanceo.
  En pruebas reales esto mejoró días específicos con déficit (ej. +3 puntos de contestación
  en un caso) sin afectar ningún otro día. Nota importante: Sábado y Domingo suelen usar casi
  toda su gente disponible por lo alto de su demanda — si un día parece "con mucha gente",
  antes de asumir que sobra vale la pena revisar cuántos empleados tienen disponibilidad
  real ese día (Personal → Disponibilidad), porque puede que ya se esté usando casi el 100%
  de quien puede trabajar esa fecha. (Corregido un bug real: este pase no aplicaba el tope
  de 7h de Domingo al evaluar los cambios, dejando pasar turnos de 8h ese día en algunos
  casos — detectado revisando un PDF real generado, no en pruebas sintéticas).

  **Elegir qué hora atender primero por escasez, no solo por déficit bruto**: dentro de
  cada día, el motor solía atender primero la hora con MÁS déficit en número absoluto, sin
  mirar cuánta gente quedaba disponible para cubrir cada hora. Esto dejaba mal paradas las
  horas con pocos candidatos aunque su déficit no fuera el más grande (ej. la apertura a
  las 11:00, que solo alcanzan unos pocos por su disponibilidad) — para cuando el motor por
  fin les tocaba turno, esos pocos candidatos ya habían sido usados en otra hora. Ahora se
  pondera el déficit entre cuánta gente puede cubrir esa hora específica, así que las horas
  escasas se atienden primero, antes de que se queden sin candidatos. Confirmado con un caso
  real: de 1 sola persona entrando a las 11:00 el Martes pasó a 4, y el % de contestación
  estimado de ese día subió de 76.3% a 95.7% en la misma semana.

  **Cada asesor tiene máximo 1
  turno por día y al menos 1 día de descanso a la semana garantizado** (si su disponibilidad
  cubre los 7 días, el sistema le reserva uno, repartiendo los descansos entre toda la
  semana en vez de que todos descansen el mismo día, y rotando semana a semana quién
  descansa qué día). El día de descanso se elige por **carga relativa** (demanda entre
  cuánta gente hay disponible ese día, no solo la demanda absoluta) — un día con demanda
  media pero pocos disponibles (ej. Martes) es más sensible a perder gente a descanso que
  uno con más demanda pero mucha más gente disponible (ej. Sábado); usar solo demanda
  absoluta antes subestimaba justo ese caso, dejando días como Martes con menos gente de
  la que realmente tenían disponible. **El Domingo, por defecto, nunca se ofrece como día
  de descanso** (regla de negocio) — configurable en Configuración General → "Permitir que
  el Domingo sea día de descanso" (Cumplimiento normativo laboral), por si en algún momento
  sí quieres permitirlo. Los turnos de domingo respetan un tope de 7h por el costo del
  recargo dominical (ajustable en `generador_horarios.py`, constante `DOMINGO_MAX_HORAS`).

  El sistema prefiere turnos de **máximo 6h** en los días de MENOR demanda (más eficiente,
  ajusta mejor a la demanda real), pero en los 3 días de MAYOR demanda (normalmente
  viernes-sábado-domingo) permite turnos completos — turnos cortos en un día de mucho
  volumen exigirían mucha más gente distinta de la que físicamente hay disponible ese día.
  Ajustable en `generar_horario_semana(..., duracion_preferida_max=6, n_dias_prioridad_maxima=3)`.

  **Garantía de mínimo semanal**: nadie queda por debajo de su mínimo contractual de horas
  a menos que sea genuinamente imposible (ej. no tiene ninguna disponibilidad cargada). Si
  hace falta, el sistema prefiere pasarse por 1-2h del mínimo antes que dejar a alguien
  corto — primero intenta agregarle un turno en un día libre que aún tenga disponible, y si
  ya no le quedan días libres, **extiende un turno ya existente** (o lo cambia por una
  plantilla más larga, si usas el módulo de Turnos) dentro de su ventana de disponibilidad
  real. Solo genera una alerta cuando de verdad no hay margen (ej. cero disponibilidad
  cargada para esa persona).

  **Cumplimiento normativo laboral**: cada horario generado se valida automáticamente
  contra reglas laborales estándar (`cumplimiento.py`) — máximo de días consecutivos
  trabajados (6, cruzando incluso el límite entre una semana y la siguiente usando el
  historial) y descanso mínimo entre turnos (10h). El resultado (`cumplimiento.resumen` en
  la respuesta de la API, y una hoja aparte en el Excel exportado) te dice si el horario
  cumple o qué violaciones específicas tiene.

  **Exportar a Excel**: además del PDF, puedes descargar el horario en `.xlsx` (botón
  "⬇ Descargar Excel") — con el cuadrante de turnos y una hoja de resumen ejecutivo
  (costo, % de servicio, cumplimiento normativo), lista para nómina o para que un
  supervisor la edite/imprima.

  **Meta de servicio y Shrinkage ya no se eligen manualmente en Horarios** — quedan fijos
  en 95% de meta y 10% de shrinkage (los valores de operación normal), para simplificar la
  pantalla. La única palanca de ajuste rápido es el toggle **"⚡ Modo ultra productividad"**
  (Encendido por defecto): con él encendido, la meta baja a 85% — menos colchón de servicio,
  más ocupación real por agente, menos gente necesaria para el mismo volumen. Apágalo si
  quieres volver a la meta normal de 95%. Si tu equipo ya está limitado por disponibilidad
  específica por hora (no por el total de horas semanales), el modo puede cambiar muy poco
  el resultado real — el sistema no inventa disponibilidad que no existe. (Ambos valores
  siguen siendo ajustables como parámetros por defecto del sistema en Configuración
  General, para quien necesite algo distinto de fábrica).

  ⚠️ **Si usas el módulo de Turnos (plantillas)**: asegúrate de incluir al menos una
  plantilla de 7h o menos que aplique a Domingo — si todas tus plantillas duran 8h, ninguna
  cabrá en el tope dominical y ese día quedará muy mal cubierto (lo confirmamos en pruebas:
  Domingo pasó de 0% a 76% de servicio con solo agregar una plantilla de 7h).

  Debajo del cuadrante hay una **gráfica de cobertura por hora** (con pestañas por día) que
  compara requeridos vs. programados hora por hora — las barras en rojo marcan dónde no
  se llegó a cubrir toda la demanda, útil para entender rápido dónde y por qué quedan huecos.

  Los resultados incluyen un indicador de **"Horas/sem promedio por asesor"** (solo entre
  quienes efectivamente quedaron con turno esa semana), útil para revisar de un vistazo si
  el reparto de horas quedó razonable.

  **Descargas para el equipo (sin valores en $)**: además de "Descargar PDF" y "Descargar
  Excel" (que sí muestran costos, para uso interno/gerencial), hay botones **"PDF equipo"**
  y **"Excel equipo"** que generan la misma información pero sin ninguna columna ni cifra
  monetaria — pensados para enviar directo a los asesores, que no necesitan ver el costo de
  nómina.

  También puedes ajustar el **shrinkage** (el % de las horas pagadas que NO es atención
  real: baños, breaks, capacitación, ausentismo) desde un selector — por defecto 10%,
  pensado para operaciones sin breaks formales y con poca capacitación. Si tu operación sí
  maneja breaks/capacitación más frecuentes, súbelo a 25-30%. Este valor afecta
  directamente cuánta gente calcula el sistema que necesitas: a menor shrinkage, menos
  personal recomendado (porque se asume que cada quien pasa más tiempo real en el teléfono).

  Un panel desplegable ("¿Cómo calcula el sistema cuántos asesores hacen falta?") explica
  toda la lógica de Erlang C en lenguaje simple, con ejemplo numérico incluido.
  La meta de servicio ahora también incluye **98% y 100%** — el sistema te avisa en pantalla
  si eliges alguna de estas porque son metas extremas: en pruebas, 100% pidió hasta 4x más
  agente-horas que 95% con apenas 8% de ocupación real (la gente sin hacer nada la mayor
  parte del turno). Con un equipo de tamaño fijo, pedir 100% puede incluso EMPEORAR el
  resultado real (el algoritmo persigue picos imposibles en vez de optimizar con lo que
  hay) — úsalo solo para ver el techo matemático, no como meta operativa.
  - **Festivos**: si la semana incluye un festivo colombiano (Ley Emiliani incluida), el
    sistema lo detecta solo y usa el patrón histórico de festivos anteriores en vez del
    patrón normal de ese día de la semana — se avisa en pantalla cuál festivo es y si hay
    o no histórico suficiente para ajustarlo bien.
  - **Rotación justa**: el sistema recuerda (tabla `historial_turnos`) quién trabajó qué
    día en semanas anteriores, y da prioridad a quien MENOS lo ha trabajado recientemente
    al momento de armar el cuadrante — así no siempre le tocan los mismos turnos a la
    misma gente, dentro de lo que la disponibilidad de cada quien permita.
- **Historial**: ya **no se guarda automáticamente** al generar — solo cuando le das al
  botón "💾 Guardar este horario en el Historial" dentro de Horarios (uno por semana, el
  más reciente reemplaza al anterior), con quién lo generó, cuándo, y con qué parámetros.
  **Si generas un horario y tratas de salir de la pestaña sin guardarlo, el sistema te
  avisa** (con la opción de salir igual si de verdad no lo necesitas) — y mientras tanto el
  botón de guardar queda resaltado con un pulso suave para que no se te pase. Botón "Ver"
  para volver a cargarlo tal cual quedó, sin tener que regenerarlo.
  **"Comparar con real"**: una vez la semana ya pasó y subiste el Excel de llamadas de esa
  semana, este botón compara lo que planeaste contra lo que realmente pasó (% de
  contestación real vs. planeado, día por día) y te da sugerencias de ajuste en texto plano
  — **ninguna se aplica sola**, quedan ahí para que decidas si las usas la próxima vez que
  generes una semana parecida. Si todavía no hay llamadas reales cargadas para esa semana,
  te lo dice claramente en vez de inventar un resultado.
- **Comparar**: corre hasta 3 configuraciones distintas (meta de servicio, shrinkage,
  proyección) para la misma semana y las pone lado a lado — % de contestación, costo,
  horas-persona, cumplimiento normativo. Resalta en verde el mejor valor de cada fila.
  Útil porque a veces el resultado no es intuitivo (ej. una meta de 85% puede terminar
  dando mejor % de contestación real que una de 95%, si el equipo ya está al límite).
- **Notificaciones** (🔔 botón circular flotante en la esquina superior derecha, visible en
  cualquier vista): alerta proactivamente sobre disponibilidad sin revisar, asesores sin
  cédula, festivos en los próximos 14 días, violaciones de cumplimiento normativo en el
  último horario generado, y brecha de personal detectada. Se actualiza solo cada 5 minutos.
  Cada alerta tiene botón **"Ver"** (te lleva directo al módulo donde se resuelve) y
  **"Descartar"** (deja de aparecer, guardado en el navegador — vuelve a salir si recargas
  desde otro navegador/equipo, ya que es local a cada uno).
- **Configuración General** (solo superadmin): 22 parámetros del sistema que antes estaban
  fijos en el código y ahora son editables sin tocar nada:
  - **Turnos**: horario operativo, tope de horas dominicales, máximo de turnos por asesor
    por día, duración preferida de turno, días con prioridad máxima en la demanda.
  - **Pronóstico y rotación**: factor de ponderación de semanas recientes (modo
    automático), segundos meta para contestar (Erlang C, estándar 20s), semanas de
    historial para la rotación justa, y un **margen de seguridad** (agentes extra por
    hora) — con advertencia honesta en pantalla: en pruebas, con un equipo ya al límite
    de capacidad, subir este margen *empeoró* el % de contestación real en vez de
    mejorarlo, porque inflar el "requerido" sin agregar gente real solo reparte distinto
    la misma escasez. Un panel desplegable en esta vista explica qué palanca tocar según
    lo que busques (contestar más llamadas vs. ser más robusto ante picos).
  - **Cumplimiento normativo**: máximo de días consecutivos y descanso mínimo entre turnos.
  - **Nómina y seguridad**: hora de inicio del recargo nocturno, duración de la sesión.
  - **Nuevo asesor**: horas mín/máx por defecto (día y semana) — se usan tanto si creas un
    empleado sin especificarlas como al precargar el formulario "+ Nuevo asesor".
  - **Metas por defecto**: servicio/shrinkage/ocupación que se precargan al abrir Horarios.

  Los cambios aplican desde el próximo horario que generes — quedan registrados en Auditoría.
- **Brecha de Personal**: compara la demanda (Erlang C) contra la capacidad actual del
  equipo, hora por hora, te dice cuántos asesores adicionales se recomiendan contratar, y
  tiene un botón para **descargar el reporte en PDF** (con logo y branding) listo para
  presentar a gerencia. Las "franjas más críticas" se ordenan por **déficit relativo** (%
  de gente que falta en esa hora específica), no por número absoluto — así un día con
  mucha demanda total (ej. Domingo) no tapa a uno más chico que en el fondo está
  proporcionalmente igual o peor (ej. Martes a las 11:00, que puede estar 57% corto aunque
  el número bruto sea menor). Al buscar candidatos, prioriza que su disponibilidad real
  cubra esas franjas específicas — más horas totales a la semana no ayuda si no calzan ahí.
- **Mi cuenta**: cambiar tu contraseña, subir una foto de perfil (se comprime en el
  navegador antes de guardarse, máx. ~500KB) y elegir cómo quieres que te salude el sistema
  al entrar a Inicio (ej. "Buenos días, Sergio 👋" en vez de tu usuario técnico).
- **Tarifas**: ajusta el valor de la hora normal, el recargo dominical, el recargo nocturno
  y el subsidio de transporte — el cálculo de costos en "Horarios" usa estos valores de
  inmediato, sin reiniciar nada.

## Corrección: el PDF/Excel descargado podía dar números distintos a los de la pantalla (v4.5)

Reportaste que el PDF descargado mostraba datos diferentes a los de la pantalla de
Horarios (ej. 83.8% de contestación en el PDF vs. 93.1% en pantalla, con el banner
"Mostrando el horario guardado..." visible). La causa: "Descargar PDF" y "Descargar Excel"
**siempre volvían a correr el algoritmo de generación desde cero** con los parámetros de
la URL, sin importar qué había realmente en pantalla. Si la pantalla mostraba:

- un horario **guardado del Historial** (que puede haberse generado días antes, con otros
  datos de llamadas disponibles en ese momento), o
- un horario con **ediciones manuales** (turnos editados/borrados a mano) sin guardar
  todavía,

el PDF ignoraba todo eso y regeneraba un horario nuevo de cero -- dando números distintos
a los que realmente se ven en pantalla (cobertura por día, costo, horas sin cubrir, etc.).

**La corrección:** "Descargar PDF" y "Descargar Excel" ahora envían al servidor el horario
EXACTO que está en pantalla (igual que ya hacía "Guardar en el Historial") en vez de pedirle
al servidor que regenere todo de cero; el servidor arma el reporte con esos datos tal cual,
sin volver a correr el algoritmo de asignación. De paso corregí un bug relacionado: al abrir
un horario desde el Historial ("Ver"), la pantalla lo mostraba bien, pero el estado interno
de la página (`ultimoHorarioGenerado`) no se actualizaba -- eso significaba que editar un
turno a mano justo después de ver un horario del Historial podía operar sobre el horario
equivocado. Ya quedó sincronizado.

Si por algún motivo el navegador no tiene nada cargado en memoria (poco común), ambas
descargas caen de respaldo al comportamiento viejo (regenerar de cero), para que el botón
nunca se quede sin hacer nada.

**Probado:** generé un horario, edité manualmente un turno (dejando a un asesor sin turno
el Lunes, lo que cambia la cobertura real), y confirmé que tanto la pantalla recalculada
como el PDF descargado después de esa edición muestran exactamente el mismo % de
contestación (78.2% en la prueba) -- antes, el PDF viejo (regenerando de cero) daba un
número distinto para la misma semana, reproduciendo el bug que reportaste.

## Daily coverage charts más grandes (v4.5)

En el PDF de Horarios, la página "Cobertura por hora, día a día" dejaba mucho espacio en
blanco debajo de las gráficas. Las agrandé (ocupan bastante más alto de la hoja) y subí el
tamaño de letra de los títulos de cada día, las horas del eje y la leyenda, para que se
vean con más detalle sin tener que hacer zoom. Sigue cabiendo todo en una sola página.

## PDF de Horarios: rediseño visual completo, estilo "Delivery 360" (v4.4)

El diseño anterior del PDF de Horarios (portada oscura tipo "hero" en banda, tarjetas de
KPI de color sólido, gráficas de torta/dona) se reemplazó por completo con un estilo más
plano y minimalista, calcado del reporte de referencia que compartiste ("Compensaciones...
Delivery 360"):

- **Portada**: ahora es una página completa en vez de una banda — fondo oscuro con un
  panel diagonal sutil, franja roja lateral, logo, título grande, una badge roja con el
  rango de fechas de la semana, y los KPIs principales impresos en grande directamente
  sobre el fondo oscuro (no en tarjetas).
- **Páginas interiores**: franja roja fina arriba de toda la página (no la banda oscura
  completa de antes), título y subtítulo en negro/gris, y la misma badge roja con el rango
  de fechas repetida arriba a la derecha en cada sección.
- **Tarjetas de KPI**: pasaron de ser recuadros de color sólido a tarjetas planas color
  crema con un acento de color solo en el borde izquierdo, número grande en negro — igual
  que la página de "Resumen ejecutivo" del reporte de referencia.
- **"Cobertura estimada por día"**: antes era una gráfica de barras de matplotlib, ahora
  son barras planas dibujadas directamente (sin ejes ni cuadrícula), coloreadas en
  verde/ámbar/rojo según el umbral — el mismo lenguaje visual de "ranking" del reporte de
  referencia.
- **"Desglose del costo semanal"**: la dona se reemplazó por el mismo tipo de barras
  planas (una por categoría: horas normales, recargo nocturno, recargo dominical,
  transporte).
- **Cuadrante de turnos**: el encabezado de la tabla pasó de fondo negro a gris claro,
  para que combine con el resto de la página.

La gráfica de "Cobertura por hora, día a día" (los 7 días en rejilla, la de v4.3) se dejó
igual -- es una comparación de dos series por hora y una gráfica real sigue siendo la
forma más clara de mostrarla; el reporte de referencia no tiene un equivalente directo a
esa vista.

Importante: este rediseño es **solo para el PDF de Horario Semanal** (el que descargas
desde "Horarios"). Los otros PDFs del sistema (Brecha de Personal, Métricas, Personal,
Disponibilidad, Permisos, Ejecutivo) siguen con el diseño anterior -- no los toqué en este
cambio para no arriesgar nada que no pediste; si quieres que también se actualicen al
nuevo estilo, dímelo y lo hago.

**Probado:** generé el PDF con los mismos datos sintéticos de antes (8 asesores, 4 semanas
de llamadas) y revisé las 4 páginas como imagen. En el primer intento los KPIs grandes de
la portada se encimaban entre sí cuando el valor era ancho (ej. "$5,451,692" invadía la
columna de al lado) -- lo corregí haciendo que el número se encoja automáticamente si no
cabe en su columna, y envolviendo las etiquetas en vez de dejarlas en una sola línea.
Verificado de nuevo tras el ajuste: ya no hay textos encimados en ninguna de las 4
páginas, tanto en la versión con costos como en la "equipo".

## PDF de Horarios: gráficas diarias de cobertura + reporte más "ejecutivo" (v4.3)

El PDF que descargas desde Horarios ("Descargar PDF") ahora incluye una página nueva,
**"Cobertura por hora, día a día"**: los 7 días en una sola rejilla (4 columnas x 2
filas), cada uno con sus barras de Requeridos (gris) vs Programados (verde si cubre, rojo
si falta) por hora -- la misma vista que ya tenías en pantalla al cambiar de pestaña de
día en Horarios, pero ahora queda en el PDF para compartir o archivar. El resto del
reporte (portada tipo "hero" con el logo, tarjetas de KPI de colores, barra de cobertura
semanal, dona de desglose de costo, cuadrante de turnos) ya tenía ese estilo más
"ejecutivo" -- lo nuevo es específicamente esa página de detalle por hora.

Primer intento: puse las 7 gráficas como imágenes sueltas en una tabla de 2 columnas --
con 7 (impar) sobraba una celda vacía y dejaba casi toda una página en blanco. Lo corregí
armando una sola imagen con las 7 mini-gráficas ya organizadas (matplotlib `subplots`),
con la leyenda ocupando el espacio de la "8va casilla" que no tiene día -- así no compite
por espacio con las etiquetas de Domingo y no sobra página en blanco. Antes: 4 páginas
para una semana con 8 asesores. Ahora: 3.

**Probado:** generé el PDF con datos sintéticos (8 asesores, 4 semanas de llamadas con
patrón de pico realista) y revisé cada página como imagen para confirmar que las gráficas
se ven bien, la leyenda no se encima con nada, y el cuadrante de turnos sigue intacto --
tanto en la versión con costos como en la versión "equipo" (sin valores monetarios).

## Corrección: el clic para editar un turno no hacía nada (v4.2)

En v4.0, al hacer clic en una celda de Horarios para editarla a mano, el atributo
`onclick` se armaba con comillas dobles por fuera Y por dentro (`JSON.stringify` también
usa comillas dobles) -- eso cortaba el atributo a la mitad con CUALQUIER nombre de asesor,
dejando un `onclick` inválido. Resultado: la celda sí se veía resaltada al pasar el mouse
(eso es solo CSS, por la clase `turno-editable`), pero el clic no hacía nada, porque el
manejador quedaba roto antes de llegar al navegador. Se corrigió envolviendo el atributo
en comillas simples (como el resto del archivo) y escapando cualquier comilla simple que
traiga el nombre -- probado con nombres normales y con uno que lleva apóstrofe (ej.
"O'Brien") para confirmar que el HTML generado queda bien formado en ambos casos.

## Horas extra: ya no pide superadmin, y se puede aplicar a varios asesores a la vez (v4.1)

Dos cambios en "Personal" → columna "Horas extra":

- **Ya no exige credenciales de un superadmin** escritas en el momento para activar o
  desactivar horas extra de un asesor -- cualquier usuario con acceso al módulo Personal
  lo hace directamente con su propia sesión, con un clic en "Gestionar". Sigue quedando
  registrado en Auditoría y en el historial de autorizaciones (quién lo hizo, cuándo, y
  el antes/después), solo que ya no hay un segundo paso de confirmación.
- **Selección múltiple**: ahora cada fila de la tabla de Personal tiene un checkbox (y uno
  en el encabezado para seleccionar todos). Al marcar uno o más asesores aparece una barra
  con el botón "⚡ Horas extra a seleccionados", que abre el mismo modal pero aplicado a
  todos los seleccionados de una sola vez (misma cantidad de horas extra para todos) --
  antes había que entrar asesor por asesor.

Si de verdad quieres que ese cambio (activar/desactivar horas extra) siga necesitando una
segunda persona que lo confirme, avísame y lo dejamos como antes solo para esa acción --
tal como quedó ahora, cualquiera con acceso a Personal puede autorizarlas sin que nadie más
lo confirme.

**Probado:** individual (sin pedir superadmin) y masivo (2 asesores a la vez, activar y
desactivar), verificando que la base de datos y el registro de auditoría/autorizaciones
queden correctos -- end-to-end contra la app real en este entorno de pruebas.

## Corrección: autorizar horas extra / ampliar disponibilidad no se usaba, y edición manual de turnos (v4.0)

**El bug encontrado (causa raíz de "autorizo horas extra y amplío disponibilidad, pero
igual me quedan horas sin cubrir"):**

Dentro del algoritmo que llena cada día (`_procesar_dia` en `generador_horarios.py`), en
cada vuelta se elegía la hora **más urgente** con déficit (la más difícil de cubrir, ej.
la hora de apertura) y se buscaba quién podía cubrirla. El bug: si para ESA hora puntual
no había ningún asesor/plantilla que calzara, el código hacía `break` y **abandonaba
TODO el resto del día** — incluso horas con déficit que sí tenían gente disponible y
presupuesto semanal de sobra para cubrirlas. Bastaba con que una sola hora difícil (ej.
la apertura, que casi nadie alcanza por su horario de disponibilidad) no tuviera
candidato, para que ninguna otra hora de ese día se intentara cubrir en esa pasada — así
hubiera autorizado horas extra a todo el mundo o ampliado su disponibilidad: esas horas
extra nunca llegaban a usarse, porque el código ni siquiera llegaba a intentar asignarlas.

**La corrección:** ahora, cuando la hora más urgente no tiene candidato, se marca esa
hora puntual como "no cubrible en esta pasada" y se sigue intentando con las demás horas
con déficit del mismo día, en vez de rendirse con el día completo. Esto se validó con una
simulación aislada del mismo algoritmo (misma lógica exacta, antes/después): con 3 horas
de déficit donde la primera (más urgente) era imposible de cubrir pero las otras 2 sí
tenían gente disponible, **antes** del fix se cubrían 0 de 6 horas-agente necesarias;
**después**, se cubren 4 de 6 (las que sí eran posibles). Esto es justo el patrón que
describiste: un hueco puntual difícil (ej. Viernes en tu captura, con 61.3%) bloqueaba
todo lo demás de ese día, sin importar cuánta gente/horas extra hubiera disponibles.
También se corrigió un bug relacionado que solo aparece con demanda en cero para algún
día (un "No pudimos comparar `None` con un número" al revertir un rebalanceo) — no
debería afectarte con datos reales, pero quedó blindado.

**Qué SÍ se verificó:** la lógica del fix se probó de forma aislada (antes/después, con
los números exactos de arriba) y además de principio a fin contra la app real (login,
crear un asesor, generar un horario, editarlo a mano y recalcular) sin errores. **Qué NO
se pudo verificar:** el efecto exacto sobre TU semana específica (cuántas horas más se
cubren con tus 20 plantillas y tus datos reales) — eso solo se ve generando de nuevo el
horario de esa semana con los datos ya cargados (horas extra autorizadas + disponibilidad
ampliada) y comparando contra la captura que me mandaste. Si el promedio de horas/asesor
sigue bajo después de esto, el siguiente sospechoso a revisar sería si alguna de tus 20
plantillas activas realmente llega a cubrir las horas más críticas del déficit (el
sistema está en "Modo Plantillas", así que solo puede usar los bloques que ya tienes
definidos en "Turnos" — si ninguno calza con la hora crítica, ahí sí haría falta crear o
ajustar una plantilla, no solo autorizar más horas).

## Edición manual de turnos ya generados (v4.0)

Ahora, en la vista de **Horarios**, después de generar el cuadrante de la semana, puedes
hacer clic en cualquier celda de la tabla (tenga o no turno asignado) para editarla a
mano: cambiar la hora de inicio/fin, añadir un almuerzo, extender un turno, o quitarlo
por completo (queda "Libre (manual)"). Al guardar, el sistema recalcula al instante (sin
volver a correr el generador automático) la cobertura real, las horas semanales de ese
asesor, el costo y el % de servicio estimado — para que los números en pantalla siempre
reflejen exactamente lo que dejaste editado.

Limitaciones honestas de esta primera versión:
- Si una celda tenía un turno partido (2 bloques el mismo día), al editarla se
  reemplazan ambos por un único bloque — no hay (todavía) un editor para turnos
  partidos de 2+ bloques.
- La edición no vuelve a correr las reglas de disponibilidad/plantillas — es una
  anulación manual deliberada, así que el sistema no te va a impedir poner un turno
  fuera de la disponibilidad declarada de ese asesor o fuera de sus plantillas; es una
  herramienta de ajuste fino para el humano, no otro algoritmo.
- El historial usado para la "rotación justa" de semanas futuras sí queda sincronizado
  con tu edición manual (para que no afecte negativamente a quién le toca descansar
  después), pero el guardado en el Historial de horarios (botón "Guardar en el
  Historial") sigue siendo un paso manual aparte, igual que antes.
- Probado de principio a fin (crear un turno manual, verificar que el costo/horas/
  cobertura se recalculan bien, y quitarlo de nuevo) contra la app real en este entorno
  de pruebas — no contra tu base de datos real en Turso/Render.

## migrar_a_turso.py ahora tolera pegar la URL completa en --org (v3.9)

Si pegas `https://app.turso.tech/tu-organizacion/` en `--org` (fácil de hacer
copiando del navegador), el script ya lo normaliza solo y se queda con el slug —
antes eso producía un 404 confuso de la API ("no such route"), porque armaba
una URL inválida por dentro.

## Migrar tu callcenter.db actual a Turso (v3.8)

Si ya tienes datos reales en tu `callcenter.db` local (empleados, horarios generados,
usuarios, auditoría) y no quieres empezar de cero en Turso, usa `migrar_a_turso.py`:

```
py migrar_a_turso.py --token TU_API_TOKEN --org TU_ORGANIZACION --db-file callcenter.db
```

- `TU_API_TOKEN`: Turso dashboard -> ícono de cuenta -> "Account Settings" -> "API Tokens".
- `TU_ORGANIZACION`: el "slug" que aparece en la URL del dashboard.

No necesita el CLI de Turso (que en Windows pide WSL) — solo Python + `requests`,
hablando directo con la API de Turso. Trabaja sobre una copia temporal, nunca toca
tu `callcenter.db` original. Al final imprime el `TURSO_DATABASE_URL` y
`TURSO_AUTH_TOKEN` listos para pegar en Render.

**Nota de honestidad**: probé a fondo la parte de preparar el archivo (modo WAL,
checkpoint, que el original quede intacto) con datos reales. La parte que habla con
la API de Turso (crear base, crear token, subir archivo) la armé siguiendo la
documentación oficial línea por línea, pero no la pude probar de punta a punta
porque no tengo cómo crear una cuenta Turso real desde acá — es la primera vez que
corre contra el servicio real va a ser cuando tú lo ejecutes. Si algo falla, el
script te dice en qué paso fue y qué error dio Turso — mándamelo y lo ajustamos.

## Soporte para Turso (base de datos en la nube) — despliegue en línea (v3.7)

Para poder subir el sistema a Render (gratis) sin perder los datos al reiniciarse
(su disco es efímero — ver sección "Cuando quieras subirlo en línea" abajo), `db.py`
ahora puede conectarse a **Turso** (SQLite en la nube, plan gratis) en vez del archivo
local, sin que el resto del código cambie:

- Si las variables de entorno `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` **no existen**
  (tu PC, como siempre), todo funciona exactamente igual que antes — mismo archivo
  `callcenter.db`, cero cambios de comportamiento.
- Si esas variables **sí existen** (en Render), `get_conn()` se conecta a Turso a
  través del paquete `libsql`, con una capa de compatibilidad (`_Row`, `_CursorWrapper`,
  `_TursoConnWrapper` en `db.py`) que hace que el resto del código (`dict(fila)`,
  `fila["columna"]`, `.lastrowid`, etc.) siga funcionando sin tocarlo — se probó cada
  pieza de esa capa por separado antes de integrarla.
- Cada escritura hace un `sync()` hacia Turso; si Turso está temporalmente
  inalcanzable, la operación se completa igual con la caché local y solo se registra
  un aviso en el log — no se cae la app por un problema de red pasajero.
- **Ojo**: esto se probó a fondo contra el mecanismo (lectura/escritura/upsert/
  PRAGMA/lastrowid, todo con datos reales de Disponibilidad), pero no contra una
  cuenta Turso real todavía — eso se termina de confirmar en el primer despliegue.

## Letrero de "Meta 85%" quitado del Modo alta productividad (v3.6)

Se quitó el aviso que aparecía debajo de la tabla al encender "Modo alta productividad"
("⚡ Meta 85% — menos colchón de servicio, más ocupación real por agente..."). El toggle
sigue funcionando igual (cambia la meta de servicio de 95% a 85% al generar), solo que
ya no muestra ese texto explicativo cada vez.

## "Horas sin cubrir" vs. "necesitas contratar" — dos metas distintas (v3.5)

Caso real: el horario mostraba "11 horas sin cubrir" y, justo abajo, el simulador decía
"necesitas 3 asesores más" — números que no parecían cuadrar entre sí. **No era un error
de cálculo**: son dos mediciones contra dos metas distintas. "Horas sin cubrir" mide
contra la meta con la que generaste ESE horario (ej. 85% en Ultra Productividad);
"necesitas contratar" es un simulador aparte que compara contra la meta que tú elijas en
su propio desplegable (que además venía con 100% fijo por defecto, sin relación con la
meta real usada, lo cual generaba esta confusión casi siempre).

Corregido:
- **"Horas sin cubrir" ahora muestra la meta entre paréntesis** — ej. "Horas sin cubrir
  (meta 85%)" — para que quede claro contra qué se está midiendo.
- **El desplegable del simulador se sincroniza automáticamente** con la meta real usada
  al generar (antes siempre arrancaba en 100%, sin importar qué habías usado).
- **Si igual eliges una meta distinta**, el resultado lo dice explícitamente: "distinto de
  la meta con la que generaste este horario (85%, con la que arriba ves 'Horas sin
  cubrir')".

## Plantillas de turno: recomendación automática y activo/inactivo (v3.4)

- **Botón "✨ Recomendar plantillas"** en Turnos: corre el generador real con las
  plantillas y disponibilidad actuales, encuentra los bloques de horas donde queda
  déficit, y propone nuevas plantillas para taparlos -- respetando el mínimo/máximo de
  horas diarias configurado en Configuración General (mismo límite que ya rige para
  cualquier asesor). Las agrega marcadas con la insignia **"✨ Sugerida"**.
- **Interruptor de activo/inactivo por plantilla**: el generador solo usa las que están
  encendidas. Antes solo existía "Eliminar" (borrado permanente); ahora se puede apagar
  sin perderla, para probarla más tarde.
- **Honestidad medida, no prometida**: cada vez que usas "Recomendar plantillas", el
  sistema muestra el % de servicio estimado ANTES y DESPUÉS de agregarlas, calculado de
  verdad (no una promesa). En las pruebas, el cambio típico fue pequeño (89.1% → 89.6%,
  y en otra corrida bajó ligeramente) -- iterando varias veces el efecto no compone.
  Cuando el cambio es marginal, el sistema lo dice explícitamente: nuevas *formas* de
  turno no crean más gente ni más horas disponibles, solo reparten mejor las que ya
  existen. Si el límite real es cantidad de gente disponible en las horas críticas
  (lo más común), la palanca correcta sigue siendo Brecha de Personal, no este botón.

## Cobertura por hora — por qué "cubierto" no es "100% de servicio" (v3.3)

Un caso real: generando el Lunes con Modo Ultra Productividad (meta 85%), varias horas
tenían "programados" igual o por encima de "requeridos", pero el % de servicio real de
ese día seguía en 88-92%, no cerca de 100%. **No era un bug** — es cómo funciona Erlang C:
"requeridos" es el mínimo para llegar exactamente a la meta configurada (85% en este
modo), no un mínimo para el 100%. Verificado con cálculo independiente en Python: con 6
agentes en una hora de 81 llamadas, el service level real da ~91%, ni más ni menos.

Para que esto se entienda de un vistazo en vez de generar confusión:
- La gráfica de "Cobertura por hora" ahora incluye una **línea roja con el % de servicio
  real estimado por hora** (no solo las barras de requeridos/programados), en un eje
  secundario de 0-100%.
- Una nota justo encima de la gráfica explica que "requeridos" está atado a la meta
  actual, no a un 100% implícito.
- El panel "¿Cómo calcula el sistema...?" en Horarios tiene un párrafo nuevo respondiendo
  directamente esta pregunta.

## Reporte Ejecutivo (v3.1 → v3.2 con rango de fechas)

Nuevo reporte, accesible desde el botón "📊 Reporte Ejecutivo" en Métricas
(`/api/reporte-ejecutivo/pdf`). Aplica una metodología de diagnóstico distinta a los
demás reportes:

- **Ranking de días por criticidad** (barra + semáforo verde/ámbar/rojo), combinando 3
  pilares: % de caídas, TMO y cobertura real (esta última corriendo el generador de
  horarios de verdad para una semana de referencia, no una estimación).
- **Severidad relativa al promedio del propio período, no umbrales fijos** — así, si toda
  la semana está mal, no se marcan todos los días por igual; solo el que más se aleja del
  promedio.
- **Página de diagnóstico** que nombra el día más crítico, el pilar más afectado, los
  números reales que lo sustentan, y una acción recomendada específica según cuál pilar
  falló (no una frase genérica repetida).
- Si no hay indicadores que se desvíen de forma relevante, dice explícitamente "sin
  indicadores suficientes para diagnosticar" en vez de inventar un problema.
- **Respeta el rango de fechas seleccionado en Métricas** (Desde/Hasta) — si tienes un
  rango activo ahí, el botón del reporte ejecutivo lo usa automáticamente; si no, analiza
  todo el histórico de llamadas cargado.
- Verificado con: revisión visual página por página, y un cálculo independiente en SQL
  crudo que confirmó que las cifras coinciden con las que ya usa el reporte de Métricas en
  todo el sistema (mismo método de agregación: total de abandonadas ÷ total de llamadas,
  no promedio de porcentajes diarios).

## Diseño visual (v3.0)

- **Tarjetas de KPI de color sólido** en los PDFs, con esquinas redondeadas y un detalle
  decorativo en la esquina — estilo dashboard financiero moderno, inspirado en una
  referencia que compartió el usuario. Cada tarjeta usa un color de una paleta ampliada
  (rojo KFC, ámbar, verde, azul, morado, teal) según si el dato es de estado (verde/ámbar/
  rojo) o neutral (color variado para diferenciarlas a simple vista).
- **Donut chart** para el desglose de costo semanal en el reporte de Horario, con el total
  en el centro del anillo y la leyenda con porcentajes al lado — reemplaza la barra
  apilada anterior.

## Diseño visual (v2.9)

- **PDFs rediseñados por completo**, con gráficas reales en vez de solo tablas:
  - Tipografía Poppins (registrada en reportlab y matplotlib), encabezado tipo "hero"
    oscuro con acento rojo, tarjetas de KPI con acento de color por umbral (verde/ámbar/
    rojo, mismos que el dashboard web).
  - **Horario Semanal**: gráfica de cobertura por día + desglose de costo en barra
    apilada por categoría.
  - **Brecha de Personal**: gráfica de requerido vs. programado real por día, coloreada
    por estado.
  - **Métricas**: las gráficas de tendencia y por hora con mejor diseño, más un **mapa de
    calor hora × día** nuevo — de un vistazo se ve dónde se concentran las llamadas.
  - **Personal, Disponibilidad, Permisos**: mismo sistema visual para consistencia; en
    Disponibilidad cada celda lleva el color de su tipo (verde=completa, azul=rango,
    gris=no disponible, rojo=sin información).
  - Los 7 endpoints de PDF (`/api/empleados/pdf`, `/api/disponibilidad/pdf`,
    `/api/permisos/pdf`, `/api/horario/pdf` con y sin costos, `/api/brecha-personal/pdf`,
    `/api/metricas/pdf`) se probaron uno por uno contra el servidor real.

## Diseño visual (v2.8)

- **Bug crítico corregido**: en el primer login de la sesión, la pestaña Personal (y
  cualquier vista que dependiera de que `mostrarApp()` terminara de correr) podía quedar
  vacía sin ningún aviso. La causa: `/api/login` no incluía el campo
  `modulos_permitidos` en su respuesta (a diferencia de `/api/me`, que sí lo incluye), así
  que llegaba como `undefined` en vez de `null` — y una comparación estricta (`!== null`)
  no lo detectaba, entrando a un bloque que intentaba usar `.includes()` sobre algo que no
  existía, lo cual cortaba la ejecución antes de cargar los datos. Corregido en ambos
  lados: el backend ahora manda el campo siempre, y el frontend usa una comparación que
  cubre los dos casos.

## Diseño visual (v2.7)

- **Responsivo en celular**: el sistema no tenía ninguna adaptación a pantallas chicas —
  ahora el menú lateral se convierte en un panel deslizante (botón hamburguesa arriba a la
  izquierda), las tablas permiten scroll horizontal en vez de romperse, y formularios/
  tarjetas se apilan en una columna.
- **Personal ya se puede editar**: antes solo se podía agregar la cédula o eliminar —
  faltaba el botón de editar aunque el backend ya lo soportaba.
- **Disponibilidad rediseñada**: el modo "Rango" no alcanzaba a mostrar las 2 horas
  completas en las tarjetas angostas del diseño anterior — ahora cada día es una fila de
  ancho completo, con espacio de sobra para los campos de hora.
- **Login con mostrar/ocultar contraseña**: ícono de ojo dentro del campo.

## Diseño visual (v2.5)

- **Modo oscuro/claro**: botón junto a la campanita de notificaciones (arriba a la derecha,
  visible en cualquier vista). Se recuerda entre sesiones (guardado en el navegador) y no
  hay parpadeo al recargar la página.
- **Menú lateral con íconos y agrupado por lógica real**: "Datos base", "Operación" y
  "Administración" — no es decoración, es para encontrar más rápido lo que buscas.
- **Disponibilidad simplificada**: los 4 tipos (Completa/Rango/No disponible/Sin
  información) ya no se eligen desde un `<select>` — son botones directos de un clic, con
  color por tipo. El rango de horas se ve en línea ("09:00 a 17:00") en vez de dos campos
  sueltos.
- **Configuración dividida en tarjetas** en vez de un solo bloque continuo de 22 campos —
  cada sección (Turnos, Pronóstico, Cumplimiento, Nómina, etc.) es su propia tarjeta, las
  menos usadas (Nómina, Valores por defecto de un asesor nuevo) empiezan colapsadas. El
  botón de guardar queda fijo en la parte de abajo de la pantalla mientras escribes, y se
  resalta en ámbar si hay cambios sin guardar.

Rediseño completo de la interfaz, pensado desde el propio dominio del sistema en vez de
una plantilla genérica de SaaS:

- **Login**: pantalla oscura con un patrón de barras de cobertura (el mismo motivo visual
  de "requeridos vs. programados" que usa toda la app) animándose de fondo, sobre una
  cuadrícula técnica sutil. El formulario es un panel de vidrio esmerilado, no la
  típica tarjeta blanca centrada.
- **Tipografía**: Space Grotesk para títulos y cifras grandes (más carácter técnico),
  Inter para texto de interfaz y tablas (se mantiene — sigue siendo la mejor opción para
  legibilidad en datos densos).
- **Paleta**: fondo oscuro `#14161C` (no el negro plano de cualquier plantilla), superficie
  clara neutra `#F3F2EE`, rojo de marca KFC sin tocar, un ámbar propio para advertencias
  (antes se reusaba el rojo de marca para eso, lo cual era confuso).
- **Jerarquía de tarjetas**: ya no todo es la misma cajita blanca con sombra — las tarjetas
  de datos reales llevan borde fino sin sombra; el énfasis visual se reserva para lo que
  de verdad importa (login, alertas, botones primarios).

Si quieres ajustar algún color o la tipografía, todo vive en `static/style.css` bajo
`:root` al principio del archivo — son variables con nombre, no hay que buscar valores
sueltos por todo el CSS.

## Seguridad

Auditoría hecha probando ataques reales contra el sistema (no solo revisando el código):

- **Fuerza bruta en el login**: bloqueado tras 5 intentos fallidos seguidos (15 minutos),
  por usuario. Probado: al 6to intento devuelve 429, y ni siquiera la contraseña correcta
  pasa mientras dure el bloqueo.
- **XSS (inyección de HTML/JavaScript)**: probé crear un empleado con el nombre
  `<img src=x onerror=alert(1)>` y el sistema lo aceptaba sin validar — como esos nombres
  se muestran tal cual en varias tablas, esto habría ejecutado JavaScript en el navegador
  de cualquiera que las viera, incluido un superadmin. Corregido: se rechazan los
  caracteres `< > { }` en nombre de empleado, usuario, plantilla de turno y nombre a
  mostrar del perfil, antes de guardarlos.
- **Contraseñas**: PBKDF2-SHA256 con 100,000 iteraciones y salt único por usuario (nunca en
  texto plano, nunca el mismo hash para la misma contraseña en 2 cuentas distintas).
- **Sesión**: token firmado criptográficamente (clave de 32 bytes generada al azar la
  primera vez, guardada localmente), cookie `httpOnly` (no accesible desde JavaScript) y
  `SameSite=Lax` (protección básica contra CSRF). El flag `secure` (exigir HTTPS) es
  configurable con la variable de entorno `COOKIE_SECURE=true` — déjala apagada mientras
  corres local, actívala cuando despliegues en línea con HTTPS.
- **Inyección SQL**: revisadas las 4 funciones que arman la sentencia `UPDATE` dinámicamente
  (empleados, tarifas, usuarios, plantillas) — los nombres de columna siempre vienen de
  modelos con campos fijos (Pydantic), nunca de un diccionario con claves controlables por
  quien hace la petición, así que no hay forma de inyectar SQL por ahí. Los valores siempre
  van parametrizados (`?`), nunca concatenados directo en el SQL.
- **Archivos subidos** (Importar Datos): antes solo se validaba la extensión del nombre
  (`.xlsx`), lo cual cualquiera puede falsificar. Ahora también se valida: (1) el tamaño,
  leído en bloques de 1MB con tope de 20MB, para que un archivo enorme no tumbe el
  servidor; (2) la firma real del archivo — un `.xlsx` de verdad es un ZIP y siempre
  empieza con los bytes `PK`, así que un archivo con esa extensión pero contenido distinto
  se rechaza antes de intentar procesarlo. Probado con un archivo de texto renombrado a
  `.xlsx` (rechazado) y uno de 25MB (rechazado).
- **Fotos de perfil**: se restringieron a JPEG/PNG/WEBP/GIF — se excluyó explícitamente
  SVG, que puede llevar `<script>` o `onload=` embebido y ejecutar JavaScript.
- **CORS**: no hay ninguna política configurada, que es lo correcto acá — el navegador
  bloquea por defecto cualquier petición desde otro origen distinto a este mismo servidor.

Esto cubre los vectores de ataque más comunes contra una app como esta. Ningún sistema es
100% inexpugnable, pero estos son los que de verdad importan para el tamaño y uso de este
proyecto — si en algún momento lo expones directo a internet (no solo tu red local), avísame
para revisar HTTPS, firewall y limitar quién puede llegar al servidor.

## Rendimiento

Generar un horario tomaba ~935ms; con dos optimizaciones concretas (encontradas perfilando
el código, no adivinando) bajó a ~458ms — **más del doble de rápido**, mismo resultado:
1. **Caché del histórico de llamadas**: antes se releía y re-parseaba la tabla completa de
   llamadas desde SQLite 3 veces por cada generación (una por cada función que la
   necesitaba). Ahora se carga una sola vez y se cachea en memoria, invalidándose solo
   cuando el archivo de la base de datos cambia (al importar llamadas nuevas).
2. **Guardado del historial en una sola transacción**: antes, cada turno asignado
   (~119 por semana, empleados × días) abría su propia conexión y hacía su propio commit a
   SQLite. Ahora se guardan todos juntos en una sola transacción.

Consejo: si notas la app lenta en algún módulo puntual en el futuro, avísame para
perfilarlo igual que este caso -- casi siempre el problema real es distinto de lo que
parece a simple vista (en este caso, no era el algoritmo de asignación, era I/O repetido).

## Borrar llamadas cargadas (si encuentras un error en los datos)

En **Importar Datos**, debajo de las tarjetas de subida, hay una "Zona de peligro" (solo
visible para el usuario `superadmin`, por ser una acción destructiva):
- **Borrar TODO el histórico** de llamadas, para volver a cargar desde cero.
- **Borrar solo un rango de fechas**, si el error fue puntual y no hace falta borrar todo.

Ambas acciones piden doble confirmación antes de ejecutarse y no se pueden deshacer.
También puedes hacerlo por consola:
```python
from db import eliminar_todas_las_llamadas, eliminar_llamadas_rango
eliminar_todas_las_llamadas()                          # borra todo
eliminar_llamadas_rango("2026-08-01", "2026-08-05")     # borra solo ese rango
```

## Cargar datos por consola (alternativa a "Importar Datos")

Si prefieres la consola en vez de subir por el navegador:
```
py loader_disponibilidad.py "Disponibilidad_de_horarios.xlsx"
py loader_llamadas.py "llamadas_agosto.xlsx"
```
Ambos son seguros de re-correr: reconocen por nombre/hash lo que ya existe y no duplican.

También puedes generar el horario y el reporte de brecha por consola, si lo prefieres:
```
py generador_horarios.py 2026-09-07
py reporte_brecha_personal.py 2026-09-07 0.95
py costos.py 2026-09-07
```

## Estructura de archivos

```
db.py                       -> Base de datos (SQLite) y funciones CRUD
loader_disponibilidad.py    -> Lee el Excel de disponibilidad
loader_llamadas.py          -> Lee el Excel de llamadas (carga incremental, sin duplicar)
validar_disponibilidad.py   -> Revisa disponibilidad vs mínimos/máximos contractuales
erlang.py                   -> Motor de cálculo de personal requerido (Erlang C)
agregados_llamadas.py       -> Convierte llamadas crudas en promedios por hora/día y métricas
generador_horarios.py       -> Cruza disponibilidad + permisos + Erlang C -> cuadrante semanal
costos.py                   -> Aplica las tarifas al horario generado
reporte_brecha_personal.py  -> Excel de sustento para contratación
main.py                     -> API web (FastAPI) que expone todo lo anterior
static/                     -> Interfaz web (HTML/CSS/JS) que consume la API
callcenter.db                -> Tu base de datos (se crea sola, no viaja en el zip)
```

## Cuando quieras subirlo en línea (para que otros se conecten) — opciones gratis (2026)

Este mismo código sirve tal cual, con un matiz importante: casi ninguna opción realmente
gratis deja el archivo `callcenter.db` (SQLite) intacto entre reinicios — hay que elegir
con eso en mente. Tres caminos, de más simple a más robusto:

**1. Tu propia PC/servidor de oficina + túnel gratis (Cloudflare Tunnel)**
   100% gratis, sin límite de horas, y el SQLite queda intacto porque literalmente sigue
   corriendo en tu máquina — el túnel solo le da una URL pública (`https://...`) sin abrir
   puertos en el router. Requiere que el equipo quede encendido y conectado todo el tiempo
   que quieras que el sistema esté disponible (un PC de oficina que nunca se apaga sirve
   mejor que un laptop personal). Es la opción más simple si tienes un equipo así.

**2. Render (free) + Turso para la base de datos**
   Render aloja gratis la app (FastAPI), pero su plan free tiene **filesystem efímero**:
   cualquier archivo que la app escriba en disco (como `callcenter.db`) **se borra** cada
   vez que el servicio se reinicia o "duerme" por inactividad (a los 15 min sin tráfico,
   y tarda ~1 min en despertar con la siguiente visita). Para que los datos no se pierdan,
   hay que mover la base de datos a **Turso** (SQLite en la nube, plan gratis generoso,
   compatible casi 1:1 con el SQL que ya usa `db.py`). Implica un cambio de código en
   `get_conn()` para apuntar a Turso en vez del archivo local — lo puedo hacer cuando
   quieras dar este paso.

**3. Render/Railway de pago (~$5-7 USD/mes) o un VPS barato (Hetzner, ~$5 USD/mes)**
   La opción más confiable: sin "dormir", sin filesystem efímero, disco propio para el
   SQLite tal cual está hoy (cero cambios de código). Vale la pena si el equipo va a
   depender de esto todos los días.

Ojo con otras que suenan gratis pero ya no lo son tanto en 2026: **Fly.io** eliminó su
free tier permanente para cuentas nuevas (ahora da solo una prueba de 2 horas o 7 días);
**Railway** da apenas ~$1 USD de crédito al mes tras el bono inicial, insuficiente para
tener el sistema arriba todo el tiempo; **PythonAnywhere** free tier es para apps Flask/
Django clásicas (WSGI), no corre FastAPI de forma nativa, y hay que "revalidar" el sitio
cada cierto tiempo o se apaga solo.

No hace falta decidir esto ya — primero seguimos afinando el sistema local contigo.
