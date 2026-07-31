# Protocolo del spike técnico de aislamiento multiempresa

- **Iteración:** 3
- **Fecha de ejecución:** 2026-07-31
- **Base exclusiva:** `claridez_tenancy_spike`
- **Estado:** ejecutado; resultados sujetos a revisión del propietario

## Propósito

Comparar con PostgreSQL 17 y Django 5.2 dos estrategias para datos privados:

1. consultas y escrituras tenant-aware únicamente en la aplicación;
2. los mismos controles de aplicación más PostgreSQL Row-Level Security como defensa en
   profundidad.

El contexto de sesión persistente se incluye solo como fault injection. El spike no define el
modelo productivo de organizaciones ni selecciona una estrategia de identidad.

## Límites experimentales

Todo el código vive en `apps/api/spikes/tenancy`. La configuración normal, el frontend y la base
`claridez_local` no se modifican. Las entidades `TechnicalOrganization`,
`ApplicationTechnicalRecord`, `ApplicationTechnicalChildRecord`, `RlsTechnicalRecord` y
`RlsTechnicalChildRecord` son sintéticas. Una sexta tabla técnica prueba RLS sin política.

La relación hija representa `organization_id` y `parent_id` como columnas explícitas. Una migración
reversible añade la FK compuesta:

```text
(organization_id, parent_id) -> (organization_id, id)
```

`SeparateDatabaseAndState` mantiene el estado Django con campos soportados y declara por separado
la restricción PostgreSQL que Django 5.2 no expresa mediante una `ForeignKey` pública compuesta.

## Ciclo de vida verificable

```text
bootstrap local
  -> crear claridez_tenancy_spike con propietario claridez_migrator
  -> migrate --database=migrator
  -> conceder privilegios limitados
  -> verificar catálogos
  -> pytest sin gestión automática de base
  -> benchmark y evidencia
  -> verificar nuevamente propietarios
  -> eliminar claridez_tenancy_spike en finally
```

El runner valida PostgreSQL 17, el nombre de clúster local, UTF-8, UTC, host configurado como
loopback y el nombre exacto de la base. No elimina roles, volumen, contenedor, `claridez_local` ni
`claridez_test`.

## Contexto transaccional candidato

El helper experimental priorizado ejecuta:

```text
tenant_scope(organizacion_previamente_validada)
  -> transaction.atomic()
  -> set_config('claridez.organization_id', uuid, true)
  -> operación
  -> commit o rollback
  -> restaurar ContextVar en finally
```

Un scope interior del mismo tenant reutiliza el exterior. Un tenant distinto se rechaza antes de
SQL. `SET LOCAL` fuera de una transacción explícita se prueba, pero no se adopta. El middleware por
sí solo tampoco se adopta: con `ATOMIC_REQUESTS`, el middleware se ejecutaría fuera de la
transacción de la vista.

El lector PostgreSQL transforma ausencia, cadena vacía o UUID malformado en `NULL`. No existe UUID
global ni tenant predeterminado.

## Matriz automatizada

La suite cubre:

- A accede a A; A no distingue B de un UUID inexistente; caso recíproco B hacia A;
- ausencia, cadena vacía, UUID malformado y UUID válido de otra organización;
- misma conexión A → B y A → sin contexto;
- `CONN_MAX_AGE=0`, conexión persistente, cierre y reapertura;
- commit, rollback, excepción, `atomic` anidado y rollback de savepoint;
- dos hilos con conexiones independientes;
- `SELECT`, `INSERT`, `UPDATE`, `DELETE`, bulk, joins, ORM y SQL directo;
- relación válida y referencias cruzadas por ORM, bulk y SQL;
- intento de cambiar `organization_id`;
- `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, propietario, no propietario y tabla sin
  política;
- capacidad del migrador, aplicación y test runner;
- proceso técnico sin tenant;
- privilegios por columna y comportamiento de `save()`.

Los bypasses de aplicación —manager no filtrado, `_base_manager`, `raw()`, cursor, bulk sin servicio
y consulta olvidada— existen exclusivamente para medir riesgo residual.

## Benchmark

Se insertan datos sintéticos simétricos, con los mismos índices y la misma consulta para ambos
casos. Se ejecutan 20 calentamientos y 100 mediciones, y se informa mediana, p95 y un resumen de
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`. Es una observación local secundaria, no una predicción ni
un umbral de producción.

## Criterios de validez

- Las migraciones son ejecutadas solo por `claridez_migrator`.
- Todas las tablas siguen perteneciendo al migrador antes y después de pytest.
- Los roles de Claridez no son superusuarios, no tienen `CREATEROLE` ni `BYPASSRLS`.
- La aplicación no puede alterar tablas, políticas o privilegios efectivos.
- Las pruebas no crean otra base.
- La evidencia se guarda antes de limpiar.
- `claridez_tenancy_spike` no existe al terminar.

## Referencias técnicas

- [PostgreSQL 17 — Row Security Policies](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)
- [PostgreSQL 17 — SET](https://www.postgresql.org/docs/17/sql-set.html)
- [PostgreSQL 17 — funciones de configuración](https://www.postgresql.org/docs/17/functions-admin.html)
- [Django 5.2 — transacciones](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [Django 5.2 — conexiones persistentes](https://docs.djangoproject.com/en/5.2/ref/databases/#persistent-connections)
