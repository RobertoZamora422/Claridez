# P15 — Evidencia de implementación en curso

Fecha: 4 de septiembre de 2026. Base inspeccionada: `ef8ccc9b5beda7986ae78fdc98522ef38496fe59`.
La implementación fue autorizada explícitamente en la conversación posterior a esa base.
Este registro no es un ADR, un nuevo plan ni un acta de cierre. **P15 no está completada.**
No se ha modificado ADR 0024, ni reabierto P14, ni implementado P16. No hay commit, push,
despliegue ni cutover de estos cambios.

## 1. Diagnóstico y límite de la evidencia

Hay código nuevo de Analytics y de sus puertos fuente, pruebas aisladas y una superficie React.
PostgreSQL local en `127.0.0.1:55432` no responde. Docker Desktop no logra arrancar su motor;
su log de arranque señala un fallo al abrir el listener local `dockerInference`.
El intento no destructivo `docker desktop restart --timeout 45` terminó con código 1:
`Docker Desktop is still starting: context deadline exceeded`.
No se borraron sockets, volúmenes ni datos de Docker; tampoco se ejecutó reset de fábrica.

`check:all` se detiene en `db:check`. La suite PostgreSQL falla en el setup, antes de ejecutar
una sola aserción. **No se acredita que las migraciones, RLS, guardianes o claims funcionen en
PostgreSQL por el mero hecho de compilar o recolectar sus pruebas.** Tampoco hay evidencia de
`EXPLAIN (ANALYZE, BUFFERS)`, p95 interactivo o LCP contra una instalación funcional.

No se ha demostrado una contradicción arquitectónica con ADR 0024. Se corrigieron problemas
del código nuevo: lectura de identidad actual en una cohorte, atribución actual de sede histórica,
pérdida de moneda fijada por filtro en exports y sustitución de fechas guardadas al editar filtros.

La continuación detectó un import de Finance contrario a su frontera pública vigente: los DTO y
la mecánica neutral se reexportan ahora por `organizations.public` y Finance consume ese puerto.
Las siete pruebas de fronteras preexistentes pasan sin modificarlas. Se extendieron únicamente
las listas cerradas de capabilities/roles y rutas OpenAPI con las diez capacidades y diez rutas
P15 aprobadas; no se relajaron las aserciones de igualdad ni los permisos previos.

## 2. Frontera y catálogo presentes en código

Existe una única aplicación Django `claridez.analytics`, con composición mediante los módulos
`public` de las fuentes. No contiene ORM/SQL de las tablas privadas de esas fuentes.
Los DTO neutrales y la mecánica temporal están en `organizations.analytics_contracts` y
`organizations.analytics_values`; las fórmulas y lecturas permanecen en cada propietario.

El registry es code-defined, sin CRUD de fórmulas ni configuración tenant de contratos.
Catálogo `p15-v1`, 53 contratos `@1`, hash efectivo observado:

```text
c1c79d37cb9bd397c5012d27f048fd39debc5cd2ef1a196e2b9f7262d18d8c23
```

| Owner de fórmula | Contratos |
| ---------------- | --------: |
| Commercial       |         7 |
| CRM              |         2 |
| Scheduling       |         6 |
| Operations       |         6 |
| Receivables      |        10 |
| Finance          |        14 |
| Resources        |         6 |
| Analytics        |         2 |
| Total            |        53 |

Las dos composiciones propias son `request_to_confirmed_sale_conversion_rate@1` y
`distinct_canonical_request_person_count@1`. People proporciona resolución histórica de clusters,
no una tercera fórmula propia de Analytics. Las pruebas del catálogo contrastan IDs/versiones,
fuentes, dimensiones, capabilities, unidades y hash. **Esto no equivale todavía a reconciliar las
53 fórmulas con un dataset PostgreSQL representativo.**

## 3. Puertos y autorización

Los puertos batch nuevos materializan DTO inmutables, no devuelven ORM/QuerySet, reciben
`TenantAuthorization` y verifican la capability fuente. Incluyen coverage, motivo, procedencia,
revisiones/watermarks y particiones de moneda/unidad. Los contratos temporales F/S/SI/C/FP
exigen `as_of_at <= knowledge_cutoff_at <= executed_at` cuando hay as-of, y en cohortes además
`period_end <= as_of_at`; F rechaza `as_of_at`. El cutoff de una nueva consulta es server-side;
la reconstrucción interna usa el cutoff persistido.

Capabilities fuente añadidas:

- `interaction:read_analytics`, `task:read_analytics` y `person:resolve_analytics`: propietario,
  administrador y comercial.
- `schedule:read_analytics`: propietario, administrador, comercial y operaciones.

Capabilities Analytics: `analytics:read_dashboard`, `analytics:execute_report`,
`analytics:manage_own_report`, `analytics:manage_shared_report`, `analytics:create_export` y
`analytics:download_export`. Propietario/administrador reciben las seis; los otros tres perfiles
no reciben administración compartida. Las capacidades fuente siguen siendo conjuntivas.
Las exportaciones Finance y Scheduling conservan sus capacidades fuente de exportación.

La agenda Comercial se limita en el puerto fuente a solicitudes actualmente asignadas a la
membresía. Los bloqueos requieren además un filtro explícito de espacio perteneciente a ese
contexto. Esta es una restricción de acceso actual, no una nueva fórmula ni historia económica.
Su integración efectiva, incluyendo cambios de responsable y reautorización, sigue pendiente de
las pruebas PostgreSQL.

El DTO Scheduling incorpora una huella técnica de su ámbito de acceso. Se congela con el resultado
y se revalida antes de reconstruir/publicar/finalizar/descargar. Si el ámbito Comercial cambió,
el snapshot no concede acceso: se deniega y se requiere nueva ejecución. La comparación es
conservadora: también invalida cuando cambia el conjunto por ampliación, no solo por revocación.
Un rol con lectura de agenda organizacional sigue sujeto a todas sus capabilities fuente.

## 4. Evidencia histórica source-owned

Las adiciones son prospectivas, sin backfill funcional:

- Commercial conserva la persona de creación en `EventRequestHistory.analytics_person` mediante
  captura de fuente y FK tenant-aware. Las cohortes legacy sin esa evidencia no consultan la
  persona vigente para fingir identidad histórica.
- Scheduling conserva sedes anterior/nueva en `ScheduleEvent`; sin evidencia de sede no se
  atribuyen minutos o eventos a la sede actual del espacio. No se añade porcentaje de ocupación.
- Operations añade timestamp de registro a nuevas transiciones y un ledger de estado/responsable.
  Las verificaciones consultan definición congelada, decisiones aprobadas y eventos visibles al
  corte, no su proyección mutable actual.
- Resources captura snapshots propios de requerimientos, asignaciones e indisponibilidades en su
  ledger existente. No hay historia fabricada de los registros previos al cambio.
- Finance mantiene snapshots de cierre como autoridad; los cierres nuevos pueden incorporar
  particiones P15 solo si reconcilian con la fórmula existente. La falta de dimensiones de un
  cierre anterior degrada coverage, no recalcula ese cierre.

Estas decisiones de implementación necesitan todavía reconciliación exhaustiva sobre las fuentes
reales, incluyendo merges, correcciones, backdating, cancelaciones, reversos y ajustes de periodos.

## 5. Reportes, ejecuciones y reproducibilidad

Se implementaron definición, revisión append-only, visibilidad privada/organización, archivo
lógico, ejecución explícita idempotente y manifest. Un refresh interactivo no crea ejecución.
Una definición guardada no es snapshot. Compartir no concede capabilities fuente.

La ejecución conserva selección/revisión, versiones, catálogo/hash, filtros/dimensiones, tiempos,
zona, coverage y huellas de procedencia. Los periodos Finance cerrados y completos se reconsultan
desde su snapshot único inmutable y deben producir el mismo hash. Las demás familias conservan
únicamente sus resultados acotados en esa ejecución; no hay tabla de hechos, caché transversal o
read model compartido. Una divergencia falla con error de integridad.

Motivo de esta materialización acotada: `created_at/recorded_at <= knowledge_cutoff_at` no implica
que la transacción que insertó el hecho ya fuera visible al consultar. Un commit posterior puede
hacer aparecer luego un hecho registrado antes del cutoff. Los puertos actuales no tienen una
frontera durable de visibilidad transaccional; reconsultarlos solo por timestamp y detectar una
divergencia no garantiza poder exportar exactamente el resultado original. Se conservan los
puntos agregados de la ejecución, no copias del ledger. El caso de cierre Finance observado es
distinto porque su snapshot es único, inmutable y no vuelve a calcular hechos posteriores.

La estrategia y equivalencia se prueban aisladamente; la equivalencia completa entre una ejecución
real, sus fuentes y la descarga aún no está acreditada en PostgreSQL.

## 6. Exportaciones y elección de dependencias

No se añadió ninguna dependencia; los locks existentes se mantienen sin cambios.

- CSV: `csv` de la biblioteca estándar, UTF-8 con BOM y escape de texto type-aware. Un Decimal
  negativo no se convierte en texto por protección contra formula injection.
- XLSX: paquete OOXML mínimo determinista con `zipfile` y XML, celdas numéricas, booleanas,
  temporales y `inlineStr`, hojas Resultados/Procedencia. No se escriben fórmulas. Se rechazan
  números que Excel no puede representar con precisión de 15 cifras; CSV conserva su decimal
  exacto. Esto evita truncamiento silencioso, pero limita ese caso de XLSX.
- PDF: se reutiliza WeasyPrint 69.0 ya fijado por el repositorio, con perfil Linux canónico y
  fuentes DejaVu, etiquetas de accesibilidad y denegación de recursos externos. No se reutiliza
  estado, storage, jobs ni expedientes de Documents. **El PDF canónico no pudo renderizarse ni
  verificarse visualmente en el contenedor durante esta ejecución.**

Referencias consultadas para la elección: [ECMA-376](https://ecma-international.org/publications-and-standards/standards/ecma-376/),
[precisión de Excel](https://support.microsoft.com/en-US/Excel/keeping-leading-zeros-and-large-numbers)
y [API de WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html).

La identidad del renderer incluye código de construcción del dataset/serialización/proceso y
versión WeasyPrint. Falta ensayar estabilidad binaria en el runtime canónico completo y todos sus
reintentos. No se exportan nombres, teléfonos, correos, notas, mensajes ni documentos personales;
las dimensiones son las referencias y categorías declaradas en los contratos.

## 7. Storage y worker

Puerto de storage privado de Analytics y adaptador local en `.runtime/analytics`, independiente
de P9. Key opaca determinista por organización/identidad/formato, publicación con hard-link
condicional de staging sincronizado, sin overwrite. Reintento idéntico compara bytes/hash/tamaño;
divergencia produce fallo terminal. Regenerar con otra identidad genera otra key.

El worker usa ledger PostgreSQL propio, enumera organizaciones, abre scope de infraestructura de
un tenant, reclama con `SKIP LOCKED`, confirma claim, ejecuta I/O sin transacción abierta y
finaliza en el tenant correcto. Revalida usuario/membresía/capabilities antes de generar, antes de
publicar y al finalizar/descargar. Hay lease, reclaim, backoff, intentos append-only y auditoría.
El renderer corre en proceso acotado por timeout. No se añadió Redis, Celery, broker ni BYPASSRLS.

Compose añade perfil `analytics` y settings/entrypoint propios, reutilizando únicamente la receta
de imagen canónica existente. Los comandos `analytics:start/stop/status/logs/worker:once` están en
`package.json`. La configuración Compose valida, pero el contenedor no se construyó ni arrancó.

## 8. API y OpenAPI

Superficie bajo `/api/v1/organizations/{organization_id}/analytics/`: catálogo, query de dashboard,
reportes/revisiones/archivo, ejecuciones, exports/estado/descarga privada. Sesión, CSRF, serializers
cerrados, idempotencia y validación de contratos/tiempos/capabilities.
Los cuatro historiales HTTP devuelven `{results, next_cursor}`: keyset por creación/UUID, cursor
firmado vinculado a organización/membresía/colección, hasta 50 candidatos y 512 KiB por página,
sin COUNT global ni OFFSET. El filtrado de capabilities se repite por página y no impide continuar
si una página intermedia contiene solo registros no autorizados. El cursor vence tras 24 horas.
OpenAPI se genera y valida con `--fail-on-warn`, sin warnings observados.
La API autenticada real, CSRF y todas las negativas HTTP aún necesitan ejecución con PostgreSQL.

## 9. Frontend y revisión visual

React carga Analytics de forma diferida dentro de Workspace. Incluye presets por perfil, fechas
civiles IANA, selección de contratos/dimensiones/filtros, KPIs/gráficos/tablas, coverage/unidad,
estados de vacío/error/no disponible/no calculable/no aplicable, reportes/revisiones, ejecución e
historial paginado de exports/descarga reautorizada. React no calcula fórmulas de negocio.
La edición de filtros conserva instantes exactos de una revisión, incluso rangos que no empiezan
a medianoche. Cambiar fechas comunes se comunica explícitamente.

La carga del catálogo tiene error visible y reintento. Un cambio de organización oculta de inmediato
el catálogo anterior, incluso antes del cleanup del efecto; una respuesta tardía no restaura el
tenant previo. Se prueban rechazo 401/403/404, error de red, reintento y cambio de tenant.

Revisión por navegador con el fixture sintético aislado `p15-visual.html?frame=1`:

- Viewport 320 × 850: ancho útil 305 px por scrollbar; `scrollWidth = clientWidth = 305`.
- Viewport 1280 × 900: `scrollWidth = clientWidth = 1265`; dos columnas de 612,4 px.
- Región tabular enfocable: foco observado, outline sólido y desplazamiento horizontal con
  flecha derecha. La tabla permanece desplazable sin desbordar la página.

La habilidad de revisión por interfaz llevó a corregir el mínimo de ancho **solo en páginas P15**
y a preservar tablas legibles/desplazables en móvil. El fixture usa datos sintéticos, no persiste
comandos, no forma parte de la entrada productiva de Vite y no demuestra LCP, backend real ni
compatibilidad completa con un lector de pantalla.

## 10. Migraciones e integridad

DDL nuevo: Analytics 0001/0002; Commercial 0009; Scheduling 0010; Operations 0019/0020;
Resources 0007. Analytics tiene ocho tablas privadas con organización, FKs tenant-aware,
`ENABLE + FORCE RLS`, privilegios acotados y guardianes de inmutabilidad/identidad/estado.
No se concede DELETE/TRUNCATE libre sobre ledgers. El bootstrap de privilegios contempla P15.
Las migraciones existentes P14 no se reescriben; no hay backfill funcional P15.

`makemigrations --check --dry-run` informa `No changes detected`, con warning por no poder
consultar el historial de la base. Esto **no prueba instalación ni migración desde P14**.

## 11. Límites numéricos presentes y rendimiento no acreditado

| Límite implementado                      |                         Valor |
| ---------------------------------------- | ----------------------------: |
| Métricas por query                       |                            53 |
| Filas materializadas de query            |                         2.000 |
| Payload interactivo de query             |                       512 KiB |
| Filas del serializador tabular de export |                        25.000 |
| Columnas de export                       |                            32 |
| Caracteres por celda                     |                         4.000 |
| Bytes por artefacto                      |                        20 MiB |
| Filas PDF                                |                         1.000 |
| Tiempo configurado por export            |                         120 s |
| Lease                                    |                         180 s |
| Intentos máximos                         |                             5 |
| Backoff                                  | 5 s exponencial, máximo 300 s |
| Historial HTTP por página                |       50 candidatos / 512 KiB |

El límite de query sigue acotando la ejecución que alimenta un export; 25.000 filas del
serializador no implica que la API permita ejecutar ese volumen. Falta verificar los presupuestos
de payload sobre todas las respuestas reales. El timeout del renderer es terminable; falta
acreditar el máximo de pared de todo el job incluyendo consultas y publicación bajo carga/fallos.

Hay ahora un generador reproducible `tests/p15_dataset.py` y un arnés explícito
`tests/performance/p15_benchmark.py`, todavía sin ejecución PostgreSQL válida. No hay Qmax
medido por endpoint, EXPLAIN/índices acreditados ni tiempos de export observados sobre ese volumen.
**p95 < 500 ms y LCP móvil < 2,5 s permanecen sin demostrar.**
El tamaño de bundle y el tiempo de build no se presentan como sustitutos de esos objetivos.
No se introdujo warehouse, materialized view, caché ni read model para eludir esa validación.

### Dataset y criterios fijados, aún no acreditados

`p15-representative-v1` crea dos tenants para el fan-in y un tercero aislado para el escenario de
historial. Todos sus hechos se crean por comandos fuente, sin desactivar triggers/RLS ni alterar
timestamps de registro. Los UUID e instantes varían por ejecución; valores, proporciones y conteos
son deterministas. La ventana de conocimiento captura el lote efectivamente creado, no simula
años de historia registrada. Los intervalos de agenda son disjuntos a seis horas de distancia.

| Dominio / hecho                                                          | Conteo esperado por tenant |
| ------------------------------------------------------------------------ | -------------------------: |
| People / personas sintéticas                                             |                        240 |
| Commercial / solicitudes                                                 |                      2.400 |
| Commercial / versiones emitidas y aceptadas                              |                        600 |
| CRM / interacciones outbound                                             |                      2.400 |
| CRM / tareas                                                             |                      1.200 |
| Scheduling / raíces confirmadas                                          |                        300 |
| Operations / preparaciones; ejecuciones completadas                      |                   300; 150 |
| Receivables / obligaciones; pagos; aplicaciones                          |              300; 300; 300 |
| Finance / periodo abierto; planes; costos; gastos; salidas de caja       |      1; 300; 300; 300; 300 |
| Resources / recursos; recepciones; movimientos                           |                24; 24; 792 |
| Resources / requerimientos; asignaciones                                 |                   300; 300 |
| Analytics, escenario historial / reportes; revisiones; ejecuciones; jobs |            75; 149; 75; 75 |

El arnés verifica los conteos contra tablas reales antes de medir. El perfil pequeño de reconciliación
(`p15-smoke-v1`, 16 solicitudes, dos recursos) no se presenta como prueba de carga representativa.
El escenario todavía debe ampliarse con periodos cerrados/ajustes, incidencias/fases y distribuciones
históricas exigidas; este dataset no sustituye los fixtures funcionales completos de las 53 métricas.

Presupuestos de aceptación code-defined en `tests/p15_measurement.py` (no cifras observadas):

| Ruta / operación                   |         Qmax | Payload máximo |
| ---------------------------------- | -----------: | -------------: |
| Catálogo                           |           24 |        128 KiB |
| Dashboard, incluso selección de 53 |          110 |        512 KiB |
| Cada historial/revisiones          |           24 |        512 KiB |
| Crear ejecución                    |          130 |        520 KiB |
| Consultar ejecución                |           50 |        520 KiB |
| Crear reporte / revisar / archivar | 36 / 40 / 32 |         64 KiB |
| Crear export / estado              |      36 / 24 |          8 KiB |
| Descargar export                   |           36 |         20 MiB |

Se cuentan también sesión, transacción, actor, Membership y GUC; el test de reconciliación acota
adicionalmente el fan-in a 96 sentencias dentro de la autorización. La carga usa ocho clientes,
tres warmups y 25 muestras por cliente: 200 muestras por perfil, sin mezclar perfiles para ocultar
uno lento. Se exige p95 por rango más próximo estrictamente menor a 500 ms. La ruta usa Client
Django con CSRF real y rol PostgreSQL `claridez_app`: mide procesamiento HTTP, no transporte de red.
El arnés contempla dos jobs simultáneos por formato CSV/XLSX, claim→publicación→finalización menor
a 120 s y comprobación SHA-256 al descargar. PDF canónico y LCP se validan aparte y siguen pendientes.

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` se ejecuta en una pasada separada, dentro del mismo
scope/rol/tenant de la consulta fuente, antes de medir latencia. El registro conserva owner, hash
SQL, árbol de nodos, filas, tiempos y buffers; excluye SQL, parámetros, Filter/Output/Index Cond.
El JUnit de `npm run test:p15:performance` guarda observaciones incluso ante fallo de presupuesto.
El artefacto actual solo contiene el fallo de conexión del setup, no mediciones.

## 12. Comandos y resultados observados

Desde la raíz del repositorio:

```powershell
uv --directory apps/api run pytest tests/test_p15_pagination.py tests/test_p15_context.py tests/test_p15_contracts.py tests/test_p15_sources.py tests/test_p15_storage.py tests/test_p15_renderers.py tests/test_p15_finance.py tests/test_p15_query.py tests/test_p15_reproducibility.py tests/test_p15_api.py tests/test_p15_render_process.py tests/test_p15_measurement.py --no-cov -q --tb=short
```

Resultado observado: **307 passed in 2.56s**, código 0. Son pruebas aisladas; no reemplazan la suite
completa de backend. Incluyen catálogo, tiempos/DST, composiciones, mocks de fuentes, renders
CSV/XLSX, límites, storage/races y proceso renderer. Hubo fallos intermedios de fixtures/lint;
se corrigieron y se reejecutaron los controles pertinentes.

| Comando                                             | Resultado observado                                                     |
| --------------------------------------------------- | ----------------------------------------------------------------------- |
| `npm run test:web`                                  | 20 archivos, 58 pruebas; 6,53 s; código 0                               |
| `npm run build`                                     | Django sin incidencias; OpenAPI sin warnings; Vite 68 módulos; código 0 |
| `npm run format:check`                              | 469 archivos Python y Prettier correctos; código 0                      |
| `npm run lint`                                      | Ruff/ESLint sin errores ni warnings; código 0                           |
| `npm run typecheck`                                 | mypy: 466 archivos sin incidencias; TypeScript correcto; código 0       |
| `npm run check:locks`                               | 98 paquetes; locks consistentes; código 0                               |
| `docker compose --profile analytics config --quiet` | Código 0; no arranca contenedores                                       |
| `git diff --check`                                  | Código 0                                                                |
| `npm run db:migrations:check`                       | Sin cambios; warning de conexión; código 0                              |
| `npm run check:all`                                 | Código 1 en `db:check`; no completada                                   |

Build observado: chunk Analytics 25,77 kB / gzip 8,19 kB; CSS Analytics 4,52 kB / gzip 1,39 kB.
Bundle principal JS 451,52 kB / gzip 114,59 kB. Estas cifras no acreditan LCP.

Se amplió el diagnóstico a todas las pruebas recolectadas que no declaran base de datos. El comando
siguiente selecciona solo esa pasada diagnóstica; no modifica pytest.ini, marcas, puertas oficiales
ni el requisito de ejecutar después la suite completa:

```powershell
uv --directory apps/api run python -c 'import pytest
class WithoutDatabase:
    def pytest_collection_modifyitems(self, config, items):
        excluded = [item for item in items if item.get_closest_marker("django_db") is not None or item.get_closest_marker("integration") is not None or any(name in item.fixturenames for name in ("db", "transactional_db"))]
        items[:] = [item for item in items if item not in excluded]
        config.hook.pytest_deselected(items=excluded)
raise SystemExit(pytest.main(["--no-cov", "-q", "--tb=short"], plugins=[WithoutDatabase()]))'
```

Resultado: **368 passed, 346 deselected in 7.37s**. La primera pasada detectó siete fallos por
ausencia de las adiciones P15 en las listas cerradas de capabilities/roles y OpenAPI. Se agregaron
los valores aprobados explícitos conservando todas las aserciones previas; la reejecución pasó.

```powershell
uv --directory apps/api run pytest -m integration tests/integration/test_p15_analytics_postgresql.py --collect-only --no-cov -q
```

Resultado: **13 tests collected in 0.76s**. Incluye RLS/roles/tenants, revisiones, equivalencia,
doble claim, expiración, revocación, crash después de publicación, hash rival y migración.

```powershell
uv --directory apps/api run pytest -m integration tests/integration/test_p15_analytics_postgresql.py --no-cov -q -x --tb=short
```

Resultado: **1 warning, 1 error in 4.92s**, código 1. Falla el setup de la primera prueba con
`django.db.utils.OperationalError: connection timeout expired`; ningún cuerpo de prueba ejecutado.
La suite backend completa también se encontró bloqueada en setup. No se han rebajado las puertas
oficiales, su selección de pruebas, auditorías ni `--durations=20` de integración.

Auditorías: hubo un fallo intermedio por timeout del endpoint npm de advisories. El reintento
`npm audit --workspace @claridez/web --audit-level=high --fetch-timeout=30000 --fetch-retries=1`
también terminó con código 1 por `audit network timeout`. La última ejecución de `npm run audit`
sí completó con código 0: `pip-audit` informó `No known vulnerabilities found` y npm
`found 0 vulnerabilities`. No se añadieron dependencias ni se cambiaron lockfiles.

Nuevos intentos PostgreSQL:

```powershell
uv --directory apps/api run pytest -m integration tests/integration/test_p15_reconciliation_postgresql.py --no-cov -q -x --tb=short
npm run test:p15:performance -- -x --tb=short
```

Reconciliación: **1 warning, 1 error in 3.76s**, código 1 en setup. Rendimiento:
**1 warning, 1 error in 4.38s**, código 1 en setup. Ambos por
`django.db.utils.OperationalError: connection timeout expired`. La nueva prueba consulta los 53
contratos y añade aserciones sobre 35 resultados/familias conocidos, pero ninguna se ejecutó.
La recolección de esa prueba y los dos escenarios de benchmark dio **3 tests collected in 0.58s**.

## 13. Requisitos todavía no satisfechos

No es correcto describir lo restante como solamente pulsar «ejecutar pruebas». Faltan:

- Completar y ejecutar fixtures de reconciliación PostgreSQL de las 53 métricas y todos los casos
  temporales/financieros/recursos/identidad exigidos por ADR y la aprobación.
- Validar y, si las pruebas lo requieren, corregir migraciones desde cero/P14, guardianes,
  privilegios, RLS, carreras, reautorización y recuperación completa del worker.
- Completar la experiencia de filtros/dimensiones autorizadas donde el código actual todavía
  exige UUID, y validar la paginación implementada contra la base real.
- Validar PDF canónico, determinismo binario, privacidad de logs y formatos ante todos los límites.
- Ejecutar y ampliar el dataset/arnés de rendimiento, acreditar Qmax, índices source-owned,
  EXPLAIN, concurrencia, duración de exports, p95 y LCP; responsive dentro de Workspace real
  y revisión accesible completa. Completar medición de comandos que hoy solo tienen presupuesto.
- `npm run check:all` y auditorías finales completas en el árbol definitivo.

## 14. Roadmap y Handoff

No se han actualizado, conforme a la instrucción de hacerlo solo cuando P15 esté realmente
completa. Sus frases anteriores a esta conversación sobre autorización de P15 no describen la
aprobación explícita recibida ahora. Este archivo registra el avance sin alterar esas fuentes ni
declarar un cierre inexistente.

## 15. Continuidad exacta

El siguiente trabajo sigue siendo **completar y validar P15**. Hace falta recuperar el motor Docker
Desktop y PostgreSQL local, conservando sus datos, para continuar la validación source-owned.
**P16 — Administración completa** continúa pendiente y no se implementó.

## Inventario de archivos

El inventario al corte de este registro se añade a continuación; no hubo archivos eliminados.

### Modificados (25)

```text
apps/api/src/claridez/commercial/models.py
apps/api/src/claridez/commercial/public.py
apps/api/src/claridez/crm/public.py
apps/api/src/claridez/finance/public.py
apps/api/src/claridez/finance/services.py
apps/api/src/claridez/operations/models.py
apps/api/src/claridez/operations/public.py
apps/api/src/claridez/organizations/capabilities.py
apps/api/src/claridez/organizations/public.py
apps/api/src/claridez/organizations/tenant_scope.py
apps/api/src/claridez/people/public.py
apps/api/src/claridez/receivables/public.py
apps/api/src/claridez/resources/models.py
apps/api/src/claridez/resources/public.py
apps/api/src/claridez/scheduling/models.py
apps/api/src/claridez/scheduling/public.py
apps/api/src/claridez/settings/base.py
apps/api/src/claridez/settings/environment.py
apps/api/src/claridez/urls.py
apps/api/tools/local_database.py
apps/api/tests/test_capabilities.py
apps/api/tests/test_organization_http.py
apps/web/src/app/Workspace.tsx
compose.yaml
package.json
```

### Creados (81)

```text
apps/api/src/claridez/analytics/__init__.py
apps/api/src/claridez/analytics/apps.py
apps/api/src/claridez/analytics/errors.py
apps/api/src/claridez/analytics/exporting.py
apps/api/src/claridez/analytics/jobs.py
apps/api/src/claridez/analytics/management/__init__.py
apps/api/src/claridez/analytics/management/commands/__init__.py
apps/api/src/claridez/analytics/management/commands/analytics_worker.py
apps/api/src/claridez/analytics/migrations/0001_initial.py
apps/api/src/claridez/analytics/migrations/0002_tenant_integrity.py
apps/api/src/claridez/analytics/migrations/__init__.py
apps/api/src/claridez/analytics/models.py
apps/api/src/claridez/analytics/pagination.py
apps/api/src/claridez/analytics/presets.py
apps/api/src/claridez/analytics/query.py
apps/api/src/claridez/analytics/registry.py
apps/api/src/claridez/analytics/render_process.py
apps/api/src/claridez/analytics/renderers.py
apps/api/src/claridez/analytics/serializers.py
apps/api/src/claridez/analytics/services.py
apps/api/src/claridez/analytics/storage.py
apps/api/src/claridez/analytics/urls.py
apps/api/src/claridez/analytics/views.py
apps/api/src/claridez/commercial/analytics.py
apps/api/src/claridez/commercial/analytics_access.py
apps/api/src/claridez/commercial/finance_evidence.py
apps/api/src/claridez/commercial/metric_inputs.py
apps/api/src/claridez/commercial/migrations/0009_p15_request_identity_evidence.py
apps/api/src/claridez/crm/analytics.py
apps/api/src/claridez/crm/metric_inputs.py
apps/api/src/claridez/finance/analytics.py
apps/api/src/claridez/finance/analytics_metadata.py
apps/api/src/claridez/finance/metric_inputs.py
apps/api/src/claridez/operations/analytics.py
apps/api/src/claridez/operations/finance_evidence.py
apps/api/src/claridez/operations/metric_inputs.py
apps/api/src/claridez/operations/migrations/0019_preparation_transition_recorded_at.py
apps/api/src/claridez/operations/migrations/0020_p15_preparation_state.py
apps/api/src/claridez/organizations/analytics_contracts.py
apps/api/src/claridez/organizations/analytics_values.py
apps/api/src/claridez/people/analytics.py
apps/api/src/claridez/receivables/analytics.py
apps/api/src/claridez/receivables/finance_evidence.py
apps/api/src/claridez/receivables/metric_inputs.py
apps/api/src/claridez/resources/analytics.py
apps/api/src/claridez/resources/metric_inputs.py
apps/api/src/claridez/resources/migrations/0007_p15_state_evidence.py
apps/api/src/claridez/scheduling/analytics.py
apps/api/src/claridez/scheduling/finance_evidence.py
apps/api/src/claridez/scheduling/metric_inputs.py
apps/api/src/claridez/scheduling/migrations/0010_p15_historical_venues.py
apps/api/src/claridez/settings/analytics_worker.py
apps/api/tests/integration/test_p15_analytics_postgresql.py
apps/api/tests/integration/test_p15_reconciliation_postgresql.py
apps/api/tests/p15_dataset.py
apps/api/tests/p15_measurement.py
apps/api/tests/performance/__init__.py
apps/api/tests/performance/p15_benchmark.py
apps/api/tests/test_p15_api.py
apps/api/tests/test_p15_context.py
apps/api/tests/test_p15_contracts.py
apps/api/tests/test_p15_finance.py
apps/api/tests/test_p15_measurement.py
apps/api/tests/test_p15_pagination.py
apps/api/tests/test_p15_query.py
apps/api/tests/test_p15_render_process.py
apps/api/tests/test_p15_renderers.py
apps/api/tests/test_p15_reproducibility.py
apps/api/tests/test_p15_sources.py
apps/api/tests/test_p15_storage.py
apps/web/p15-visual.html
apps/web/src/features/analytics/AnalyticsView.test.tsx
apps/web/src/features/analytics/AnalyticsView.tsx
apps/web/src/features/analytics/MetricCard.tsx
apps/web/src/features/analytics/analytics.css
apps/web/src/features/analytics/temporal.ts
apps/web/src/features/analytics/types.ts
apps/web/src/features/analytics/useAnalyticsCatalog.test.ts
apps/web/src/features/analytics/useAnalyticsCatalog.ts
apps/web/src/test/p15-visual.tsx
docs/architecture/P15_IMPLEMENTATION_EVIDENCE.md
```
