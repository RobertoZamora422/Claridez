# Contribuir a Claridez

## Estado actual

Claridez es un proyecto privado y propietario. El repositorio contiene toolchains reproducibles, plataforma PostgreSQL local y esqueletos técnicos mínimos, pero todavía no contiene módulos funcionales.

Toda contribución debe respetar [AGENTS.md](AGENTS.md), la [línea base del producto](docs/product/PRODUCT_BASELINE.md), los [ADR](docs/adr/README.md) y la [política de seguridad](SECURITY.md).

## Antes de realizar un cambio

1. Confirma el alcance de la iteración autorizada.
2. Revisa las fuentes de verdad aplicables.
3. Comprueba el estado de Git y preserva cambios ajenos.
4. Identifica si la propuesta altera una decisión arquitectónica.
5. No presupongas reglas de negocio todavía no especificadas.

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
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run check
npm run check:all
```

`npm run format` aplica correcciones y debe ser idempotente. `check:all` requiere PostgreSQL local iniciado y preparado. `npm run audit` se ejecuta por separado porque requiere acceso a servicios externos.

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
