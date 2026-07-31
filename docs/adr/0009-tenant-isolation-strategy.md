# ADR 0009 — Estrategia de aislamiento multiempresa

- **Estado:** Propuesto
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

ADR 0003 exige pertenencia organizacional para todo dato privado y dejó RLS pendiente de evidencia.
La Iteración 3 comparó rutas tenant-aware de aplicación con las mismas rutas reforzadas por
PostgreSQL RLS, usando roles no propietarios, transacciones y conexiones reutilizadas.

## Decisión propuesta

Para cada futura tabla privada se propone aplicar controles en dos capas:

1. autorización previa, servicios y consultas tenant-aware en Django;
2. RLS fail-closed mediante `organization_id` como defensa en profundidad.

El contexto se establecería solo después de validar al actor y la organización:

```text
transaction.atomic()
  -> set_config('claridez.organization_id', uuid_validado, true)
  -> operación tenant-aware
  -> commit o rollback
```

El rol de ejecución deberá ser no propietario y no tendrá `BYPASSRLS`. Las relaciones privadas
deberán imponer en PostgreSQL una FK o restricción equivalente que incluya `organization_id`.

Esta sección es una propuesta técnica, no una decisión aceptada ni autorización para crear modelos
productivos.

## Decisiones que no se proponen

- RLS como sustituto de autenticación, membresías, permisos o validación de organización activa.
- Contexto de tenant persistente a nivel de sesión.
- UUID especial para datos globales.
- `ATOMIC_REQUESTS` o middleware como integración definitiva.
- `BYPASSRLS` para aplicación, workers o soporte.
- Privilegios por columna o triggers como regla general.
- Conversión automática del código del spike en código productivo.

## Evidencia

- Las rutas de aplicación soportadas aislaron, pero los bypasses deliberados leyeron ambas
  organizaciones y permitieron escrituras cruzadas.
- RLS filtró ORM y SQL directo; `WITH CHECK` rechazó escrituras cruzadas y cambios de tenant.
- El comportamiento fue fail-closed sin contexto y con contexto malformado.
- `SET LOCAL` quedó limpio tras commit, rollback y excepción, incluso con conexión reutilizada.
- El contexto de sesión contaminó el uso siguiente de la conexión.
- `ENABLE` permitió bypass al propietario; `FORCE` aplicó la política también al propietario.
- La FK compuesta impidió relaciones cruzadas independientemente de formularios o servicios.
- RLS siguió un UUID válido ajeno cuando se le proporcionó: la autorización previa sigue siendo
  obligatoria.
- El benchmark local no mostró una señal que justifique decidir por rendimiento.

La evidencia completa está en
[TENANCY_SPIKE_RESULTS.md](../architecture/TENANCY_SPIKE_RESULTS.md).

## Alternativas evaluadas

### Solo aislamiento en aplicación

Menor complejidad PostgreSQL, pero una omisión en manager, SQL, bulk, comando o job puede exponer o
modificar datos. Las pruebas demostraron esos bypasses. No se recomienda como única barrera.

### Aplicación más RLS

Reduce el impacto de una consulta olvidada y cubre SQL directo. Añade disciplina transaccional,
políticas, diagnóstico y casos especiales para propietario/migrador. Es la opción recomendada para
revisión.

### Contexto de sesión con reset manual

Fue contaminante con conexiones reutilizadas. Se propone rechazarlo.

### Base o esquema por organización

No fue parte del spike y permanece diferido salvo futuros requisitos contractuales, regulatorios o
de escala.

## Consecuencias si se acepta

- Cada operación tenant-aware necesitará una transacción exterior explícita.
- La integración deberá impedir scopes anidados con tenants distintos.
- Tests, comandos, workers, Admin y migraciones de datos necesitarán APIs y casos de prueba
  explícitos.
- La base y la aplicación conservarán filtros redundantes de forma deliberada.
- Las consultas y planes deberán observarse conforme aparezcan cargas representativas.

## Decisiones pendientes antes de aceptar

- Punto exacto donde se valida autorización y se abre el scope en Django.
- Uso productivo de `FORCE ROW LEVEL SECURITY` y política para migraciones de datos.
- Tratamiento de Django Admin, soporte interno y procesos globales auditados.
- Aislamiento de archivos, exports, logs, cachés y futuros trabajos asíncronos.
- Convención productiva de relaciones compuestas y ergonomía ORM.

## Estado del código experimental

El directorio `apps/api/spikes/tenancy` no es candidato directo a producción. Tras la revisión se
eliminará o se reimplementarán selectivamente conceptos aprobados. Mientras este ADR siga
`Propuesto`, RLS no está adoptado por Claridez.
