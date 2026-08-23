# Registros de decisiones arquitectónicas

Un Architecture Decision Record (ADR) conserva el contexto, la decisión y las consecuencias de una elección arquitectónica significativa.

## Cuándo crear un ADR

Se debe crear o actualizar un ADR cuando una decisión:

- Sea costosa de revertir.
- Afecte varias áreas del sistema.
- Modifique el aislamiento multiempresa.
- Introduzca una dependencia, proveedor o componente operativo importante.
- Establezca una convención transversal.
- Reemplace una decisión previamente aceptada.

No se requiere ADR para detalles locales fácilmente reversibles que no alteren una decisión vigente.

## Numeración y nombres

- Los ADR se numeran secuencialmente con cuatro dígitos.
- `0000-template.md` es la plantilla y no representa una decisión.
- El nombre debe describir la decisión con palabras separadas por guiones.
- Un ADR publicado no se renumera.

## Estados

- **Propuesto:** pendiente de aprobación; no autoriza implementación.
- **Aceptado:** decisión aprobada y vigente.
- **Rechazado:** alternativa evaluada que no fue adoptada.
- **Reemplazado:** decisión histórica sustituida por otro ADR enlazado.

Dentro de un ADR aceptado se deben distinguir además:

- **Decisiones aceptadas:** alcance actualmente aprobado.
- **Aspectos provisionales:** nombres o direcciones de trabajo aún no definitivos.
- **Asuntos diferidos:** decisiones postergadas de forma consciente.
- **Validación pendiente:** spike, prueba o evaluación requerida antes de adoptar una opción.

Un ADR no debe presentar un asunto provisional, diferido o pendiente de spike como una decisión definitiva.

## Índice actual

| ADR                                                                       | Estado                              | Tema                                                        |
| ------------------------------------------------------------------------- | ----------------------------------- | ----------------------------------------------------------- |
| [0001](0001-monorepo-and-modular-monolith.md)                             | Aceptado                            | Monorepo, monolito modular e independencia                  |
| [0002](0002-application-technology-baseline.md)                           | Aceptado                            | Familias tecnológicas y contrato de API                     |
| [0003](0003-multitenancy-foundations.md)                                  | Aceptado con aspectos provisionales | Fundamentos multiempresa                                    |
| [0004](0004-defer-asynchronous-infrastructure.md)                         | Aceptado                            | Diferimiento de infraestructura asíncrona                   |
| [0005](0005-incremental-observability.md)                                 | Aceptado                            | Observabilidad incremental                                  |
| [0006](0006-reproducible-toolchains.md)                                   | Aceptado con asuntos diferidos      | Toolchains reproducibles y comandos oficiales               |
| [0007](0007-local-postgresql-platform.md)                                 | Aceptado con asuntos diferidos      | Plataforma PostgreSQL local reproducible                    |
| [0008](0008-validated-local-configuration-and-health.md)                  | Aceptado con asuntos diferidos      | Configuración local validada y endpoints técnicos           |
| [0009](0009-tenant-isolation-strategy.md)                                 | Aceptado                            | Aplicación tenant-aware más RLS como defensa en profundidad |
| [0010](0010-local-identity-and-server-sessions.md)                        | Aceptado                            | Identidad local y sesiones de servidor                      |
| [0011](0011-organizations-memberships-and-authorization.md)               | Aceptado                            | Organizaciones, membresías y autorización backend-first     |
| [0012](0012-commercial-scheduling-and-monetary-integrity.md)              | Aceptado                            | Integridad de agenda y cotizaciones comerciales             |
| [0013](0013-commercial-operations-coordination-and-integrity.md)          | Aceptado                            | Coordinación e integridad entre comercial y operaciones     |
| [0014](0014-multi-space-business-configuration-and-catalog-boundaries.md) | Aceptado                            | Multi-espacio y límites de configuración funcional P6       |
| [0015](0015-people-crm-boundaries-and-commercial-authority.md)            | Aceptado                            | Límites de people/CRM y autoridad comercial P7              |
| [0016](0016-scheduling-ownership-and-temporal-integrity.md)               | Aceptado                            | Propiedad de scheduling e integridad temporal P8            |
| [0017](0017-contractual-domain-and-documentary-evidence.md)               | Aceptado                            | Dominio contractual y evidencia documental P9               |
| [0018](0018-file-platform-and-document-processing.md)                     | Aceptado                            | Plataforma de archivos y procesamiento documental P9        |
| [0019](0019-receivables-authority-and-financial-movement-integrity.md)    | Aceptado                            | Autoridad de cuentas por cobrar e integridad financiera P10 |
| [0020](0020-finance-authority-recognition-and-operational-close-integrity.md) | Aceptado                         | Autoridad financiera operativa, reconocimiento y cierres P11 |

## Modificación y reemplazo

Si cambia una decisión central, se crea un nuevo ADR que enlaza y reemplaza al anterior. Las aclaraciones que no cambian la decisión pueden incorporarse al ADR existente con una nota fechada.
