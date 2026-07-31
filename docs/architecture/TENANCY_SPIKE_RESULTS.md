# Resultados del spike técnico de aislamiento multiempresa

- **Ejecución final:** 2026-07-31
- **Resultado:** 36 pruebas aprobadas, 0 fallidas, 0 omitidas
- **Cobertura experimental observada:** 67 %, sin umbral de calidad adoptado
- **Base final:** `claridez_tenancy_spike` eliminada
- **Decisión:** recomendación pendiente de revisión; ADR 0009 permanece `Propuesto`

## Resultado ejecutivo

La evidencia favorece combinar controles tenant-aware en la aplicación con PostgreSQL RLS como
defensa en profundidad. Las rutas soportadas de aplicación aislaron correctamente, pero todos los
bypasses deliberados pudieron leer dos filas y las escrituras no validadas por bulk y SQL directo
atravesaron el límite. Con RLS, los mismos accesos directos quedaron aislados o rechazados.

RLS no resolvió autorización: al establecer deliberadamente el UUID válido de otra organización,
la política mostró sus filas. Por tanto, la aplicación debe validar membresía y permiso antes de
establecer el GUC.

## Plataforma y propiedad observadas

- PostgreSQL informó `server_version_num=170010`.
- Todas las tablas `claridez_spike_*` y `django_migrations` pertenecieron a
  `claridez_migrator` antes y después de las pruebas.
- `claridez_app` y `claridez_test_runner` fueron no propietarios.
- Ningún rol Claridez fue superusuario ni tuvo `CREATEROLE` o `BYPASSRLS`.
- Solo `claridez_test_runner` conservó `CREATEDB`, según el contrato local de Iteración 2; no lo
  utilizó en el spike.
- `claridez_app` no pudo crear o alterar tablas, eliminar políticas ni conceder privilegios
  efectivos.
- `claridez_migrator` pudo ejecutar DDL y fue el único rol que aplicó migraciones.

## Matriz de aislamiento

| Caso | Solo aplicación | Aplicación + RLS |
|---|---|---|
| A lee A / B lee B | permitido por ruta soportada | permitido |
| A intenta B / B intenta A | no encontrado por ruta soportada | no encontrado incluso por manager no filtrado |
| sin contexto | manager soportado: 0; servicio de escritura falla | lectura ORM/SQL: 0; escritura falla |
| UUID vacío o malformado | validación de aplicación necesaria | helper devuelve ausencia segura; 0 filas |
| manager no filtrado / `_base_manager` | 2 filas potencialmente expuestas | política limita a 1 o 0 |
| `raw()` / cursor directo | 2 filas potencialmente expuestas | política limita a 1 o 0 |
| bulk sin servicio | escritura cruzada posible | `WITH CHECK` rechaza |
| SQL directo sin servicio | escritura cruzada posible | `USING` y `WITH CHECK` aíslan |
| proceso técnico sin tenant | 2 filas visibles por bypass | 0 filas |
| lookup ajeno vs. inexistente | indistinguible en servicio | indistinguible también en base |

No se registraron payloads ni identificadores de la organización ajena en el resumen permanente.

## Transacciones y conexiones

- `SET LOCAL` ejecutado en autocommit perdió el valor al terminar esa sentencia; no sirve como
  scope de una operación posterior.
- El patrón `transaction.atomic()` + `set_config(..., true)` conservó el tenant durante la
  operación y lo eliminó tras commit, rollback y excepción.
- Esto se verificó con `CONN_MAX_AGE=0` y con una conexión persistente de 60 segundos.
- En la misma conexión persistente, A → B mantuvo separación y A → sin contexto devolvió cero.
- Cerrar y reabrir produjo contexto ausente. El PID cambió en la observación local, pero no se usa
  como identificador estable.
- Un rollback de savepoint restauró el GUC exterior; una excepción en `atomic` interior preservó el
  scope exterior.
- El scope interior con el mismo tenant reutilizó contexto. Un tenant distinto se rechazó antes de
  ejecutar SQL.
- Dos hilos usaron conexiones y contextos independientes.
- El fault injection de contexto de sesión (`is_local=false`) contaminó el consumidor siguiente y
  expuso una fila. La variante queda explícitamente rechazada.

## CRUD, integridad y RLS

- `USING` y `WITH CHECK` cubrieron `SELECT`, `INSERT`, `UPDATE`, `DELETE`, bulk y SQL directo.
- Una tabla con RLS habilitado y sin política negó lectura y escritura por defecto.
- Con `ENABLE ROW LEVEL SECURITY` sin `FORCE`, el propietario vio dos filas sin contexto.
- Con `FORCE ROW LEVEL SECURITY`, el propietario vio cero filas sin contexto y una con contexto.
- Una actualización de datos ejecutada por el migrador afectó dos filas con `ENABLE` sin contexto,
  cero con `FORCE` sin contexto y una con `FORCE` y tenant explícito.
- El rol no propietario `claridez_test_runner` obedeció las políticas.
- Las FK compuestas rechazaron relaciones cruzadas mediante ORM, bulk y SQL directo.
- Los joins tenant-aware válidos funcionaron en ambas familias.
- Las unicidades por `organization_id` permitieron la misma clave externa en organizaciones
  distintas y rechazaron duplicados dentro de una.
- Cambiar `organization_id` fue rechazado por `WITH CHECK` en RLS y por privilegio de columna en la
  variante experimental de aplicación.
- No fue necesario un trigger.

## Privilegios por columna

La prueba retiró a `claridez_app` el permiso de actualizar `organization_id`. Un `save()` normal de
Django intentó incluir esa columna aunque no hubiera cambiado y falló; `save(update_fields=[...])`
funcionó. El control protege la columna, pero vuelve frágil el uso normal del ORM. No se recomienda
adoptarlo como control general sin una abstracción muy estricta y evidencia adicional.

## Benchmark local

Datos: 1.000 filas por organización y por estrategia, mismos índices, misma búsqueda exacta, 20
calentamientos y 100 mediciones.

| Estrategia | Mediana | p95 | Plan resumido | Buffers |
|---|---:|---:|---|---|
| Solo aplicación | 1,7835 ms | 2,7760 ms | `Index Scan` por unicidad organización/clave | 3 hits, 0 reads |
| Aplicación + RLS | 1,7458 ms | 2,3811 ms | `Result` → `Index Scan` equivalente | 3 hits, 0 reads |

Los tiempos son ruido local plausible y no muestran una ventaja de rendimiento de RLS. Ambos planes
usaron el índice compuesto y devolvieron una fila. No se define umbral ni se extrapola a producción.

## Recomendación propuesta

1. Mantener autorización previa, servicios y consultas tenant-aware en la aplicación.
2. Añadir RLS a cada tabla privada como defensa en profundidad, con rol de ejecución no propietario
   y sin `BYPASSRLS`.
3. Usar un scope transaccional exterior explícito con `SET LOCAL`, nunca contexto de sesión.
4. Considerar `FORCE ROW LEVEL SECURITY` para tablas privadas; diseñar migraciones de datos y
   operaciones excepcionales antes de aceptarlo.
5. Imponer integridad relacional mediante claves y unicidades compuestas en PostgreSQL.
6. No adoptar por defecto privilegios de actualización por columna ni triggers.

Esta recomendación no autoriza implementación. Deben resolverse en revisión el punto de integración
en Django, comportamiento del Admin, migraciones de datos, soporte excepcional, archivos y procesos
sin tenant.

## Destino del experimento

- Eliminar modelos, migraciones, settings, runner, benchmark y bypasses tras aprobar o rechazar la
  decisión.
- Reimplementar selectivamente el scope, managers y servicios después de diseñar organizaciones y
  autorización productivas; no copiarlos automáticamente.
- Conservar este resultado, el protocolo, el modelo de amenazas y ADR 0009 como evidencia.

El detalle generado permanece local en `tmp/tenancy-spike/` y está ignorado por Git.
