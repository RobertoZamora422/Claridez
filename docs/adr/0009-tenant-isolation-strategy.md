# ADR 0009 — Estrategia de aislamiento multiempresa

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

ADR 0003 exige pertenencia organizacional para todo dato privado. La Iteración 3 comparó rutas
tenant-aware de aplicación con las mismas rutas reforzadas por PostgreSQL Row-Level Security
(RLS), usando roles no propietarios, transacciones y conexiones reutilizadas.

La evidencia confirmó que los filtros de aplicación son necesarios para autorización y ergonomía,
pero una omisión en una consulta, un bulk o SQL directo puede atravesar el límite organizacional.
RLS redujo ese riesgo y se comportó de forma fail-closed sin contexto. También confirmó que RLS no
puede decidir si un actor está autorizado a usar un identificador de organización válido.

## Decisiones aceptadas

### Dos capas obligatorias

Cada tabla privada deberá aplicar controles deliberadamente redundantes:

1. autenticación, autorización, servicios y consultas tenant-aware en Django;
2. RLS mediante `organization_id` como defensa en profundidad frente a omisiones de aislamiento y
   consultas ejecutadas sin contexto.

El rol normal de aplicación será no propietario de las tablas privadas, no tendrá `BYPASSRLS` y no
podrá alterar tablas, políticas ni privilegios. Las políticas deberán incluir controles de lectura
y escritura equivalentes a `USING` y `WITH CHECK`.

`OrganizationSettings`, aceptada por ADR 0011, es la primera entidad privada productiva con RLS.
Su implementación fue escrita de forma independiente y no convierte el código del spike en código
productivo.

### Límite autorizado de tenant

`authorized_tenant_scope` será el único límite soportado para una operación privada. La operación
completa deberá ocurrir dentro de una transacción exterior explícita y usar contexto local a esa
transacción:

```text
authorized_tenant_scope(actor, organization_reference, required_capability)
  -> transaction.atomic()
  -> helper de infraestructura establece
     set_config('claridez.organization_id', organization_id, true)
  -> valida organización, membresía activa y capacidad
  -> ejecuta validaciones y consultas privadas
  -> materializa la respuesta
  -> commit o rollback
```

El identificador recibido solo permite intentar abrir el scope; no demuestra membresía ni
autorización. El helper de bajo nivel que establece el GUC pertenecerá a infraestructura y no será
accesible desde vistas, serializers ni código de dominio ordinario. Esas capas solo podrán invocar
la abstracción autorizada.

Toda validación que dependa de datos organizacionales, toda consulta privada y toda materialización
de respuesta —incluida la evaluación de querysets diferidos y de datos del serializer— deberá
completar dentro de `authorized_tenant_scope`. No se devolverán querysets, iteradores ni objetos
lazy para evaluarlos después de cerrar el scope.

Un scope anidado podrá reutilizar el mismo tenant. Deberá rechazar un tenant distinto antes de
ejecutar la operación. Se rechaza el contexto persistente a nivel de sesión de PostgreSQL y no se
adopta `ATOMIC_REQUESTS` ni middleware por sí solo como límite de autorización.

### Límite real de RLS

RLS no es autenticación, autorización de membresía ni una defensa absoluta frente a ejecución SQL
arbitraria bajo el rol de aplicación. Ese rol puede establecer técnicamente el GUC de una
organización conocida; si lo hace, la política filtra correctamente para ese valor, pero desconoce
si el actor debía usarlo. Por ello, RLS nunca sustituye la validación backend-first dentro del
scope autorizado.

Las restricciones de unicidad y referencialidad también pueden revelar que existe una colisión en
otro tenant aunque RLS oculte sus filas. El diseño deberá:

- preferir unicidades y relaciones compuestas con `organization_id` cuando el concepto sea local;
- realizar validaciones tenant-aware sin usarlas como única defensa ante concurrencia;
- traducir conflictos de base a errores genéricos que no revelen identificadores ni datos ajenos;
- probar colisiones intra-tenant y entre al menos dos organizaciones.

Las relaciones entre datos privados deberán imponer en PostgreSQL una FK o restricción equivalente
que incluya `organization_id`. No existirá un UUID especial para datos globales.

## Aspectos provisionales

- El nombre `authorized_tenant_scope` podrá ajustarse antes de ser API estable, pero no su
  responsabilidad ni su exclusividad como límite de operaciones privadas.
- La ergonomía ORM concreta para claves y relaciones compuestas deberá conservar las restricciones
  efectivas en PostgreSQL.

## Asuntos diferidos

- Acceso transversal de soporte, que requerirá autorización reforzada, alcance temporal, razón y
  auditoría; no usará un tenant global.
- Aislamiento de archivos, exportaciones, cachés, logs y futuros trabajos asíncronos, que deberá
  extender la misma frontera organizacional cuando esos componentes existan.
- Requisitos que pudieran justificar una base o un esquema por organización.

## Validación productiva

La primera migración privada comprueba:

- `ENABLE` y `FORCE ROW LEVEL SECURITY`, política simétrica y propietario migrador sin
  `BYPASSRLS`;
- ausencia de filas sin contexto, invisibilidad cruzada y rechazo de escrituras mediante
  `WITH CHECK`;
- restricción arquitectónica de imports del helper privado del GUC;
- materialización dentro del scope y evaluación diferida cerrada fuera de él;
- errores genéricos y casos negativos con dos organizaciones para ORM, SQL directo, bulk,
  relaciones, rollback y conexiones reutilizadas;
- el procedimiento explícito para futuras migraciones de datos bajo la misma política.

## Alternativas consideradas

### Solo aislamiento en aplicación

Se rechaza como única barrera. Las rutas soportadas aislaron, pero los bypasses deliberados leyeron
o escribieron datos de ambas organizaciones.

### Aplicación más RLS

Se acepta. Añade disciplina transaccional y operativa, pero reduce el impacto de una consulta
olvidada y cubre ORM, bulk y SQL directo dentro de los límites declarados.

### Contexto de sesión con reset manual

Se rechaza porque contaminó conexiones reutilizadas. Solo se admite contexto local a una
transacción explícita.

### Base o esquema por organización

No formó parte del spike y permanece diferido salvo futuros requisitos contractuales,
regulatorios o de escala.

## Consecuencias

- La base y la aplicación conservarán filtros redundantes de forma deliberada.
- Cada operación privada tendrá una transacción exterior explícita y una frontera de autorización
  visible.
- Comandos, futuros workers y migraciones de datos necesitarán APIs y casos de prueba específicos;
  no podrán reutilizar silenciosamente el helper de bajo nivel.
- Las consultas y planes se observarán cuando existan cargas representativas.
- La implementación de cierre de la Iteración 4 materializa esta decisión únicamente para
  `OrganizationSettings`; cada tabla privada futura requerirá su propia política y pruebas.

## Evidencia

- [Protocolo del spike de tenancy](../architecture/TENANCY_SPIKE_PROTOCOL.md)
- [Resultados del spike de tenancy](../architecture/TENANCY_SPIKE_RESULTS.md)
- [Modelo de amenazas del spike](../security/TENANCY_SPIKE_THREAT_MODEL.md)
- [ADR 0003 — Fundamentos multiempresa](0003-multitenancy-foundations.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)

## Destino del código experimental

El protocolo, los resultados y el modelo de amenazas se conservan como evidencia histórica. El
paquete `apps/api/spikes/tenancy` y sus scripts se eliminan en 4.0. Cualquier implementación
productiva deberá escribirse a partir de estas decisiones y no copiar automáticamente modelos,
migraciones, bypasses o helpers experimentales.
