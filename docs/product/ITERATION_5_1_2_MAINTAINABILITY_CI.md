# Iteración 5.1.2 — Mantenibilidad y automatización de calidad

- **Estado:** implementada y validada localmente el 1 de agosto de 2026
- **Naturaleza:** refactorización estructural sin cambios funcionales ni de esquema
- **Módulo funcional preservado:** `claridez.commercial`

## Estado anterior

La línea base previa estaba limpia y superaba `npm run check`, `npm run check:all`, `npm run
audit` y `git diff --check`. El backend tenía los casos de uso comerciales concentrados en un
`services.py` de 1270 líneas y el frontend concentraba composición, pantallas y formularios en un
`App.tsx` de 1601 líneas. El contrato OpenAPI inicial ocupaba 42333 bytes y su SHA-256 era
`2359FC1113ADF07AB9C9E5F99B389CA172A7ADD93AD700BC7E1BC5D4A4CA48ED`.

La línea base ejecutó 129 pruebas backend no integrales, 29 pruebas PostgreSQL y 3 pruebas frontend.
La cobertura backend era 85 %. La cobertura frontend inicial era 57,69 % de statements, 61,94 %
de branches, 42,62 % de funciones y 58,82 % de líneas.

## Arquitectura backend resultante

`claridez.commercial.services` es ahora un paquete y conserva el mismo punto público de importación:

```text
claridez/commercial/services/
├── __init__.py          # superficie pública estable
├── shared.py            # errores, autorización y primitivas tenant-aware compartidas
├── representations.py   # materialización autorizada de respuestas
├── people.py            # personas, normalización y revisiones
├── requests.py          # solicitudes y cierre comercial
├── quotations.py        # secuencias, versiones, líneas, emisión y aceptación
├── reservations.py      # vencimiento, confirmación y cancelación
└── availability.py      # consulta de agenda
```

La dirección de dependencias parte de `shared`, continúa por `representations` y termina en los
casos de uso. `requests`, `quotations` y `availability` reutilizan las primitivas de reserva sin
separar los límites transaccionales de aceptación, vencimiento, confirmación o cancelación. No se
introdujeron clases genéricas, contenedores de dependencias ni dependencias circulares.

### Superficie pública preservada

`claridez.commercial.services` continúa exportando estas 21 funciones con los mismos nombres y
parámetros:

```text
accept_quotation_version        list_event_requests
cancel_reservation              list_people
close_event_request             list_person_revisions
commercial_capabilities         read_event_request
confirm_reservation             read_person
create_event_request            read_quotation
create_person                   read_reservation
create_quotation                replace_quotation_draft
create_quotation_version        update_event_request
issue_quotation_version         update_person
list_availability
```

Las vistas y pruebas siguen importando desde esa superficie; ningún consumidor externo necesita
conocer la organización interna. La protección backend-first de datos personales permanece en la
materialización y sigue exigiendo `person:read`.

## Arquitectura frontend resultante

`App.tsx` pasó de 1601 a 90 líneas y conserva únicamente restauración de sesión, selección de
organización y composición raíz. La estructura resultante es:

```text
src/
├── app/Workspace.tsx
├── features/
│   ├── agenda/AgendaView.tsx
│   ├── authentication/LoginScreen.tsx
│   ├── organizations/OrganizationPicker.tsx
│   ├── quotations/QuoteEditor.tsx
│   ├── requests/{NewRequestForm,RequestDetail,RequestsView}.tsx
│   └── reservations/ReservationActions.tsx
├── shared/{components,useInitialLoad,utilities}.*
├── api.ts
├── App.tsx
├── Brand.tsx
└── main.tsx
```

`Workspace` conserva navegación, capacidades y organización activa. Las pantallas, el formulario
de persona/solicitud, el editor de cotización y los comandos de reserva tienen límites propios.
`api.ts`, el CSS, la marca, las rutas funcionales, los textos y la semántica de carga, error y vacío
no cambiaron. No se añadió router, biblioteca de estado ni dependencia.

Las pruebas de caracterización frontend se colocaron junto a selección organizacional, solicitudes
y cotizaciones. Se mantienen pruebas accesibles por rol, label y texto; no se añadieron snapshots
masivos.

## Estrategia de compatibilidad

- Una prueba nueva fija nombres y firmas de las 21 importaciones públicas del servicio.
- Las suites existentes conservan estados, transacciones, RLS, capacidades, HTTP, CSRF y OpenAPI.
- Las pruebas frontend existentes continúan recorriendo autenticación, recuperación, navegación,
  agenda, detalle, confirmación y cancelación.
- Las pruebas nuevas caracterizan selección organizacional, creación o selección inline de persona,
  edición, emisión y aceptación, carga, error y representación personal restringida.
- `makemigrations --check --dry-run` protege la ausencia de cambios de modelo.
- El OpenAPI generado se compara con el artefacto previo por bytes y SHA-256.

## Workflow de CI

`.github/workflows/ci.yml` se activa en `pull_request`, `push` a `main` y
`workflow_dispatch`. Declara únicamente `contents: read` y cancela ejecuciones obsoletas de la
misma rama o pull request.

Las acciones oficiales están fijadas a SHA completo y cada uso documenta su versión. La ejecución
usa Ubuntu 24.04, UTF-8, UTC, Node.js 24.18.1, npm 11.16.0, Python 3.13 y uv 0.12.0. Las
instalaciones son `npm ci` y `uv sync --locked`; npm y uv usan cachés derivadas de sus lockfiles.

Los checks que el propietario deberá exigir en la protección de `main` son:

1. `Calidad`
2. `PostgreSQL 17`
3. `Auditoría de dependencias`

`Calidad` ejecuta `npm run check`, `git diff --check` y `git diff --exit-code`. Esto incluye locks,
formato, lint, mypy, TypeScript, pruebas y cobertura, generación y validación OpenAPI y builds.

`PostgreSQL 17` usa la misma imagen 17.10 fijada por digest que el entorno local. Ajusta el clúster
a `claridez-local`, UTF-8 y UTC; después delega la creación de `claridez_migrator`, `claridez_app`,
`claridez_test_runner`, bases y privilegios a `tools/local_database.py`. Ejecuta preparación,
migración desde cero, verificación del entorno, `makemigrations --check --dry-run` e integración
PostgreSQL completa. Los tres roles continúan sin `BYPASSRLS` y el rol de aplicación no migra.

`Auditoría de dependencias` instala desde locks y ejecuta `npm run audit` con los umbrales ya
definidos por el repositorio. No publica artefactos ni envía el código a analizadores externos.

## Comandos locales equivalentes

```text
uv --directory apps/api sync --locked
npm ci
npm run check
npm run check:all
npm run audit
git diff --check
git diff --exit-code
```

La primera ejecución real de GitHub Actions solo ocurrirá cuando el propietario publique su commit.
La validación local no se presenta como una ejecución remota.

## Resultado y límites

No se modificaron modelos, migraciones, endpoints, OpenAPI, capacidades, RLS, estados, reglas
monetarias, snapshots, vencimiento, reservas, textos ni estilos. No se generaron migraciones y los
lockfiles permanecen intactos.

### Validación observada

- `npm run check`: aprobado en 114 s; 130 pruebas backend y 10 frontend aprobadas; formato, lint,
  mypy, TypeScript, Django, OpenAPI y ambos builds aprobados.
- `npm run check:all`: aprobado en 151,4 s; PostgreSQL `170010`, UTF-8, UTC y `claridez_app`
  verificados; 29 pruebas de integración aprobadas y ninguna migración pendiente.
- `npm run audit`: aprobado en 11,4 s; `pip-audit` sin vulnerabilidades conocidas y npm con cero
  vulnerabilidades.
- Cobertura backend: 85 %, igual a 5.1.1. Cobertura frontend: 72,48 % statements, 73,89 %
  branches, 61,47 % funciones y 73,99 % líneas; todos los valores aumentaron frente a la línea base.
- OpenAPI: 42333 bytes y SHA-256
  `2359FC1113ADF07AB9C9E5F99B389CA172A7ADD93AD700BC7E1BC5D4A4CA48ED` antes y después; la
  comparación byte a byte fue idéntica.
- `actionlint` 1.7.7 y Prettier aprobaron `.github/workflows/ci.yml` sin observaciones.
- La revisión real en navegador a 1280 × 720 y 390 × 844 no encontró desbordamiento horizontal ni
  errores de consola; los controles nativos, labels y foco visible permanecen disponibles.
- Las tres migraciones comerciales publicadas siguen aplicadas. `migrate --plan` no reportó
  operaciones; no existe migración nueva que revertir o reaplicar.

La CI automatiza los controles existentes, pero la protección de rama debe configurarla el
propietario después de que GitHub registre por primera vez los tres checks. No se modificó ninguna
configuración remota.

## Riesgos residuales y deuda técnica

- `QuoteEditor.tsx` sigue siendo el componente funcional más grande porque edición, emisión y
  aceptación comparten un estado y una secuencia estrechamente cohesionados. Separarlo sin una
  necesidad funcional podría ocultar el caso de uso.
- `api.ts` continúa como límite HTTP único y pequeño; podrá dividirse por recurso cuando exista un
  cliente OpenAPI generado o aumente de manera material.
- Las pruebas de pantalla usan un mock HTTP manual. Un servidor de contratos compartido puede
  evaluarse cuando exista un cliente generado, sin duplicar ahora el contrato backend.
- GitHub Actions queda validado estáticamente y mediante comandos locales equivalentes; su ejecución
  alojada permanece pendiente de la publicación realizada por el propietario.
