# Contribuir a Claridez

## Estado actual

Claridez es un proyecto privado y propietario. El repositorio contiene toolchains reproducibles,
PostgreSQL local, identidad y organizaciones, aislamiento multiempresa, el flujo
`claridez.commercial` de consulta a reserva confirmada y `claridez.operations` hasta ejecución
completada.

Toda contribución debe respetar [AGENTS.md](AGENTS.md), el
[Blueprint](docs/product/PRODUCT_BLUEPRINT.md), el
[Roadmap](docs/product/PRODUCT_DELIVERY_ROADMAP.md), el [Handoff](docs/PROJECT_HANDOFF.md), los
[ADR](docs/adr/README.md) y la [política de seguridad](SECURITY.md).

## Antes de realizar un cambio

1. Lee Blueprint, Roadmap y Handoff.
2. Comprueba el estado real de Git, código, migraciones y configuración.
3. Identifica la siguiente etapa incompleta y confirma su aprobación.
4. Presenta solo un plan breve y decisiones bloqueantes.
5. Identifica si la propuesta altera una decisión arquitectónica y preserva cambios ajenos.

## Cambios arquitectónicos

Una decisión significativa debe documentarse mediante ADR antes o junto con su implementación. El ADR debe explicar contexto, decisión, alternativas y consecuencias, y distinguir lo aceptado de lo provisional o diferido.

No se debe utilizar un ADR para legitimar retrospectivamente una decisión que no fue revisada.

## Dependencias

Las dependencias deben incorporarse únicamente cuando:

- Resuelvan una necesidad concreta del alcance aprobado.
- Tengan mantenimiento y compatibilidad verificados.
- Su costo operativo y de seguridad sea razonable.
- No dupliquen una capacidad ya disponible.
- Queden fijadas de forma reproducible.

Las dependencias aprobadas y su matriz se registran en `docs/architecture/TOOLCHAIN_COMPATIBILITY.md`. Los lockfiles no se editan manualmente y toda actualización debe repetir las comprobaciones oficiales y las auditorías.

## Datos, tenancy y seguridad

- No utilices datos reales en desarrollo, ejemplos o pruebas.
- No versiones secretos ni archivos locales de ambiente.
- Todo diseño de dato privado debe considerar su organización.
- Las pruebas multiempresa futuras deberán usar al menos dos organizaciones e incluir intentos de acceso cruzado.
- Reporta vulnerabilidades de acuerdo con `SECURITY.md`; nunca mediante un issue público.

## Documentación

- Mantén los documentos en español, UTF-8 y LF, salvo que una necesidad aprobada requiera otro formato.
- Usa enlaces relativos dentro del repositorio.
- No incluyas rutas absolutas del equipo de una persona.
- No edites directamente una copia controlada de marca sin actualizar su registro, hash y procedencia autorizada.
- Actualiza el índice documental cuando añadas una nueva fuente de verdad.

## Calidad

La reconstrucción de la plataforma local se documenta en [docs/architecture/LOCAL_PLATFORM.md](docs/architecture/LOCAL_PLATFORM.md). `.env` es local, ignorado y nunca debe prepararse; `.env.example` no puede contener valores secretos.

Desde la raíz se deben ejecutar, según el alcance del cambio:

```text
npm run clean
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run check
npm run check:all
```

`npm run format` aplica correcciones y debe ser idempotente. `check:all` requiere PostgreSQL local iniciado y preparado. `npm run audit` se ejecuta por separado porque requiere acceso a servicios externos.

Todo cambio destinado a integración debe superar estas cinco categorías, sin reducir sus controles:

- calidad estática: locks, formato, lint, mypy y TypeScript;
- pruebas unitarias y cobertura backend y frontend;
- build de Django, OpenAPI y Vite;
- PostgreSQL 17 real: migraciones, RLS, concurrencia e integración;
- auditoría de dependencias con los umbrales fijados.

El workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) las agrupa en tres checks. Una
vez que el propietario publique el primer commit y GitHub registre sus nombres, la protección de
`main` debe exigir exactamente:

1. `Calidad`
2. `PostgreSQL 17`
3. `Auditoría de dependencias`

La configuración remota de protección pertenece exclusivamente al propietario. Una validación
local no sustituye la primera ejecución alojada de estos checks.

El código y los scripts del spike fueron descartados en 4.0. Su protocolo, resultados y modelo de
amenazas se conservan como evidencia; una implementación productiva debe seguir los ADR aceptados
y no reconstruir automáticamente los modelos, migraciones, bypasses o helpers experimentales.

Además, toda contribución debe comprobar:

- Codificación UTF-8.
- Finales de línea LF.
- Enlaces relativos existentes.
- Ausencia de secretos y rutas locales.
- Consistencia entre decisiones y ADR.
- Estado de Git y diferencias resultantes.

## Commits y acciones externas

Los commits de Claridez son ejecutados exclusivamente por el propietario del proyecto. Los colaboradores automatizados no deben crearlos. Tampoco se deben configurar remotos, publicar ramas, abrir pull requests ni realizar despliegues sin autorización explícita. La existencia de cambios preparados localmente no implica permiso para publicarlos.

## Entrega de un cambio

El resumen final debe incluir:

- Archivos creados o modificados.
- Resultado observable de cada comprobación ejecutada.
- Diferencias entre lo solicitado y lo realizado.
- Riesgos, supuestos o validaciones pendientes.
- Roadmap y Handoff actualizados, con la siguiente etapa exacta.
