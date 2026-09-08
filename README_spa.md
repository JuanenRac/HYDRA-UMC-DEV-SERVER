<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="Banner de HYDRA-UMC-DEV-SERVER" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center"><a href="README.md">🇺🇸 English</a> | 🇪🇸 <b>Español</b> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🏗️ Servidor de Desarrollo Reproducible para Todo el Ecosistema

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Lenguaje-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Núcleo-solo%20stdlib-brightgreen.svg" alt="Núcleo solo stdlib">
  <img src="https://img.shields.io/badge/Entrega-DS01%20de%2010-367BF5.svg" alt="DS01 de 10">
</p>

> **Estado: v0.0.1, scaffolding - DS01 de 10 (contratos, límites y un
> esqueleto verificable).** Un esquema de configuración real y probado
> (`config validate`) cuya política por defecto **no concede permiso de
> despliegue a ninguna tarea**, y un descubrimiento de manifiestos de
> solo lectura (`inventory scan`) que encuentra los propios
> `hydra-umc.project.json` de este ecosistema - incluido el de este
> mismo repositorio. Todavía no existe host remoto, workspace, ejecutor
> de tareas, cola durable ni integración con un proveedor de IA - eso es
> DS02, DS04, DS05 y DS06, entregas futuras. Ver
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) para la superficie de
> comandos exacta que existe hoy.

---

## 1. 🛠️ VISIÓN TÉCNICA

HYDRA-UMC-DEV-SERVER es infraestructura de desarrollo para el ecosistema
HYDRA-UMC/URTC: un host reproducible (objetivo: una Raspberry Pi 5 o
Compute Module 5, 8GB, arrancada desde NVMe) que alojará el propio código
fuente de este ecosistema y ejecutará tareas de programación/build/test
acotadas y con permisos explícitos - tanto para personas como para
asistentes de IA. **No** es una nueva IA que entrenar, **no** es un
sistema operativo de reemplazo, y nunca decide por sí mismo que una
máquina es segura para cambiarla.

Esta entrega (DS01) trae dos piezas reales y de utilidad independiente:

1. **Esquema de configuración** (`config validate`) - tres documentos
   JSON (`HostProfile`, `ToolchainPolicy`, `TaskPolicy`), cada uno con
   validación real y una prueba negativa real por cada forma rechazada.
   El invariante que más importa desde el primer día:
   `TaskPolicy.allow_deploy` es `False` por defecto, y solo un documento
   que fije el booleano JSON literal `true` puede llegar a producir una
   política con ese permiso concedido.
2. **Descubrimiento de manifiestos** (`inventory scan`) - el mismo
   patrón real y probado que ya usa el rol edge de HYDRA-UMC-OPS-AGENT
   para encontrar y validar un `hydra-umc.project.json`, reutilizado
   aquí en vez de reescrito.

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}

$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.1", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

No hay invocación por defecto/sin argumentos más allá de la demo que
ejecuta `run.sh`, y esta entrega no tiene interfaz gráfica - ver
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) para la superficie de
comandos real y completa.

## 2. 🧱 ARQUITECTURA Y DECISIONES DE DISEÑO

- **Ninguna tarea tiene permiso de despliegue por defecto.** Es el
  criterio de aceptación literal de DS01, forzado por el propio valor
  por defecto del dataclass `TaskPolicy` - no solo dicho en prosa - y
  cubierto por una prueba dedicada para cada forma en que un documento
  podría intentar colarlo (un campo ausente, mal escrito, o un valor no
  booleano).
- **Un recolector informa de un fallo real y honesto - nunca adivina.**
  Que `scan_project_manifests()` devuelva un `ManifestScanIssue` para un
  manifiesto presente pero roto, en vez de descartarlo en silencio, es
  el patrón ya establecido en este ecosistema (ver el propio
  `inventory.py` de HYDRA-UMC-OPS-AGENT) - reutilizado aquí, no
  reinventado.
- **La propiedad de estado y las relaciones entre proyectos no las
  redecide este repositorio.** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  y [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) reproducen, sin
  reinterpretarla, la tabla de propietarios de estado del plan privado
  de preparación software y su agrupación de las 17 relaciones entre
  proyectos en necesarias/opcionales/solo-desarrollo.
- **Solo stdlib en esta entrega.** `config validate` e `inventory scan`
  no necesitan ninguna dependencia externa - una entrega futura añade
  una solo cuando su propio código realmente la necesite (un driver de
  cola durable para DS05, un SDK de proveedor de IA para DS06), nunca
  de forma especulativa.
- **Esta entrega solo valida y descubre - todavía no ejecuta nada.** No
  existe workspace, ejecución de tareas, cola, ni ninguna llamada de red
  en este repositorio todavía.

## 📂 ESTRUCTURA DE DIRECTORIOS

```
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/
│   ├── config.py        # Esquema y validación de HostProfile/ToolchainPolicy/TaskPolicy
│   ├── inventory.py     # Descubrimiento real y de solo lectura de hydra-umc.project.json
│   └── cli.py            # Punto de entrada de los subcomandos config/inventory
├── configs/
│   ├── host-profile.example.json
│   ├── toolchains.example.json
│   └── task-policy.example.json   # allow_deploy: false, publicado y probado así
├── tests/                # Pruebas reales de cada módulo anterior, incl. los configs de ejemplo publicados
├── docs/
│   ├── CLI_REFERENCE.md    # Cada subcomando, sus flags y el contrato de códigos de salida
│   ├── CONFIG_SCHEMA.md    # La forma JSON real de los tres documentos de configuración
│   ├── ARCHITECTURE.md     # Propósito, modos de trabajo, alcance inicial, disco (plan 13.1/13.3-13.5)
│   └── OPS_INTEGRATION.md  # El mapa de 17 relaciones + tabla de propietarios (plan 13.2.1/13.2.2)
├── images/                # Medios e iconos de la app
├── tools/
│   ├── build_test.py      # Comprobación de compilación no versionante
│   └── ci_validate.py     # Validación de manifiesto/CHANGELOG/docs usada por CI
├── build.sh / build.bat   # venv + instalación editable + comprobación + pruebas
├── build-test.sh / .bat   # Solo validación de build no mutante
├── run.sh / run.bat       # Demo real de inventory scan + config validate (sin argumentos), o reenvía un comando CLI real
├── bump_version.py        # Incremento "odómetro" de todo el ecosistema (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Sincroniza la versión de hydra-umc.project.json con la nativa (--sync)
```

## ⚙️ GUÍA DE COMPILACIÓN Y EJECUCIÓN

```bash
chmod +x build.sh   # una sola vez
./build.sh          # crea .venv, pip install -e ".[dev]", comprobación + pruebas
./run.sh                                  # demo real: inventory scan contra este
                                           # workspace de GitHub, luego config validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

En Windows: `build.bat`, luego `run.bat` (misma demo sin argumentos) /
`run.bat inventory scan ...` / `run.bat config validate ...`.
`build-test.sh`/`.bat` hace la misma comprobación de sintaxis Python no
mutante que ya hace el propio workflow de CI, sin tocar la versión del
proyecto ni el CHANGELOG - NO ejecuta la suite de pruebas; ejecuta
`./build.sh`/`build.bat` (o `pytest tests/` directamente) para la suite
de pruebas local completa.

**Resolución de problemas**

- `config validate` sale con código `1` y `INVALID: ...`: lee el
  mensaje - lista todos los campos que fallaron, no solo el primero.
  Revisa [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) para la forma
  exacta esperada.
- `inventory scan` reporta un problema en un directorio que esperabas
  limpio: ese directorio tiene un `hydra-umc.project.json` presente pero
  ilegible, mal formado, o le falta un campo requerido - un directorio
  sin manifiesto alguno nunca se reporta como un problema.

## 🚀 HOJA DE RUTA

Esta versión solo trae DS01. Lo que queda, en el orden propio del plan:

- **DS02 - Estación remota reproducible.** Comprobaciones previas, un
  perfil mínimo de herramientas, acceso remoto por VS Code bajo una
  identidad real.
- **DS03 - Migración conservadora.** Inventario y copia por lotes desde
  el PC del usuario con hashes, cambios locales y privacidad tratados
  explícitamente - ver la sección 13.6 del propio plan.
- **DS04 - Workspace y ejecutor acotado.** Aislamiento real por tarea:
  dos tareas nunca chocan, una ruta fuera del workspace se rechaza.
- **DS05 - Cola durable y resultados trazables.** IDs, leases, un diario
  de ejecución real que sobrevive a un reinicio.
- **DS06 - Proveedor de IA intercambiable.** Primero un proveedor falso
  determinista, después uno real autorizado.
- **DS07-DS10** - incidencias coordinadas con HYDRA-UMC-OPS-AGENT, un
  primer ciclo de reparación completamente controlado, operación/
  restauración estable, y un paquete de entrega con una evaluación
  honesta de madurez.

Nada de lo anterior existe todavía en este repositorio - ver
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para lo que cada entrega
incluye y excluye explícitamente.

## 🔗 Proyectos Relacionados

Este proyecto es parte del ecosistema de robótica HYDRA-UMC del mismo autor (JuanenRac / Electro Hobby 3D). Vale la pena conocerlos, ya que una petición podría en realidad tratarse de uno de estos en vez de este repositorio.

**Directamente Relacionados**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — es dueño del ciclo de vida de incidencias de mantenimiento (evidencia, diagnóstico, cambio aprobado por humano, despliegue canario, verificación); DEV-SERVER coordina con él en vez de reemplazarlo, y nunca aprueba sus propias tareas.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — el contrato JSON Schema compartido contra el que se validará todo intercambio de tarea/resultado entre DEV-SERVER y el resto del ecosistema, en cuanto ese contrato exista.
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — el consumidor real de un candidato construido por DEV-SERVER y aprobado por OPS-AGENT; la entrega a un nodo siempre pasa por el propio camino atómico-por-verificación de UPDATER, nunca una copia directa desde un runner.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — otro hermano de "Ecosystem Operations": construye una imagen fresca de la CM5 en vez de alojar trabajo de desarrollo.

**También Parte del Ecosistema**

*Núcleo de Hardware y Plataforma*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la placa base física del brazo robótico: host CM5 + STM32H745 de doble núcleo, orquestando hasta 8 brazos-herramienta por CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — capa de producto reproducible de Raspberry Pi OS para la CM5: agente de solo lectura, config/perfiles validados, aprovisionamiento WiFi de primer contacto.

*Backend Principal y Clientes*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — el backend real headless (REST/WebSocket) con el que habla de verdad cada cliente de control.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — panel de control web con visualización 3D multi-robot en tiempo real.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centro de mando de escritorio (PySide6) para varios servidores a la vez.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — app de control nativa Android con login biométrico y un compañero Wear OS emparejado.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — app de control iOS/iPadOS (Flutter) con sincronización WebSocket en tiempo real.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interfaz táctil nativa para la pantalla DSI de 7" a bordo, embebida en la propia CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — creador/editor gráfico de URDF de escritorio que sube modelos terminados al propio catálogo de STUDIO.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — límite de coordinación para flotas AGV/AMR vía un publicador MQTT VDA 5050 real.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordinador de célula CNC de alto nivel con acceso real a estado/byte de control GRBL.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — límite de coordinación para droides con patas/humanoides, con un emisor de comandos real para Boston Dynamics Spot.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordinador de seguridad de célula láser que lee 3 salvaguardas GPIO reales de llave/recinto/interlock.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordinador seguro de alto nivel de flujo de placas para pick-and-place OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — límite de coordinación seguro para impresoras 3D Moonraker/Klipper, con comandos de trabajo realmente controlados.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordinador de seguridad con un transporte ROS 2 rclpy real, importado de forma perezosa.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — límite de coordinación para UAVs con cámara, con un emisor de comandos MAVLink real.

*Plataforma de Herramientas URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware para la placa física Universal Robot Tool Controller, 25+ perfiles de herramienta por bus CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — herramienta gráfica de escritorio para flashear placas URTC, CAN-OTA además de SWD/JTAG de chip completo.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — herramienta de diagnóstico CAN en vivo de escritorio para placas URTC, un panel por perfil de herramienta.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternativa en navegador a URTC-TESTER vía la Web Serial API, sin instalación local.

*Nodo de Visión IA (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — hub de integración del pipeline de visión Hailo-8, con una comprobación real de disponibilidad de hardware por etapa.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registro real de modelos compilados con verificación de carga segura por arquitectura/checksum Hailo.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — pipeline GStreamer real + generador de config MediaMTX con un límite de integración HailoRT real.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — ley de corrección real de servocontrol visual basado en posición, con puerta de seguridad según el estado de zona.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — comprobación real de intrusión de zona y solicitud de E-STOP, con exigencia de frescura de calibración.

*Nodo Cognitivo de IA (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — hub de integración del pipeline cognitivo Hailo-10 (orquestación LLM/VLA/voz).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — codificación/decodificación real de action-tokens y generación de trayectoria para un modelo Visión-Lenguaje-Acción.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — front-end de voz real (VAD + parser de intención) con un relay a Watch acotado y con confirmación.
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — descomposición de tareas real basada en reglas y recuperación semántica de errores sobre códigos de error del MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — búsqueda documental real TF-IDF solo stdlib sobre la propia documentación Markdown de este ecosistema.

*Orquestación y Enjambre*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — hub de integración con un contrato real de informe de salud gRPC/Protobuf y máquina de estados de misión.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — cola de trabajos real basada en prioridad con deduplicación, sobre una API HTTP real.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — vigilante real de salud de flota basado en gRPC, con su propio retry/backoff y detección de discrepancia de identidad.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — planificador de trayectoria 3D real basado en RRT con validación real de colisión de obstáculos/espacio de trabajo.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — sincronización de estado CRDT LWW-Element-Map real, probada por propiedades para convergencia multi-célula.

*Gemelo Digital y Simulación*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — hub de integración del motor de gemelo digital, con un contrato real de sincronización de compatibilidad de versiones.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — interlock de seguridad real hardware-in-the-loop que enruta comandos entre simulación y hardware real.
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — cinemática directa real y validación de límites de junta sobre un subconjunto URDF real.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — generador procedural real de escenas 2D con exportación de anotaciones YOLO/COCO.

*Datos y Analítica*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — almacén real de series temporales con sqlite3 con una API HTTP real de ingesta/consulta.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — detector de anomalías real por FFT + línea base estadística, con monitorización de deriva.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — cálculo real de OEE/disponibilidad sobre el histórico de DATALAKE, con exportación CSV reproducible.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — pipeline real de ingesta CAN/WebSocket hacia DATALAKE, con deduplicación de secuencia.

*Pasarela Industrial*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — hub de integración que enlaza con protocolos industriales, con una capa real de lista blanca de comandos/backpressure.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — espacio de direcciones OPC-UA real, verificado con una sesión de cliente de protocolo binario real.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — broker MQTT real con autenticación opcional por cliente y ACLs de topic.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — endpoints XML reales `/probe` y `/current` de MTConnect con salida en modo degradado.

*Herramientas Complementarias*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — paneles de Resúmenes Inteligentes y Resalte de Anomalías sobre DATALAKE/ANOMALY-DETECTOR, con un respaldo estadístico honesto.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — CLI de flota con un contrato real y estable de códigos de salida, un cliente real y en vivo de la propia API de HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — app compañera WearOS con alertas hápticas reales y un relay de voz al teléfono emparejado.
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — catálogo de capacidades de adaptadores externos, GET-only por diseño.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware para un rack de montaje de placas con decodificación real de ID de herramienta y lógica de precalentamiento Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware más un compañero de visión Python real para un cabezal de inspección térmica/RGB.

---

## 📚 Documentación y Comunidad

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — cada subcomando, sus flags, y el contrato de códigos de salida.
- **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — la forma JSON real de `HostProfile`/`ToolchainPolicy`/`TaskPolicy`.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — propósito, los dos modos de trabajo, alcance inicial, y organización del disco.
- **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — el mapa completo de 17 relaciones y la tabla de propietarios de estado.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — stack técnico y guías de codificación para un pull request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — los estándares de comportamiento esperados en esta comunidad.
- **[SECURITY.md](SECURITY.md)** — cómo reportar una vulnerabilidad, y las áreas reales de foco de seguridad de este proyecto.
- **[SUPPORT.md](SUPPORT.md)** — dónde hacer preguntas y reportar errores.

## 👤 AUTOR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENCIA

GPL-3.0 (software) / CC BY-SA 4.0 (documentación) - ver [LICENSE.md](LICENSE.md).
