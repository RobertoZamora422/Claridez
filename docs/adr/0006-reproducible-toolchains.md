# ADR 0006 — Toolchains reproducibles y comandos oficiales

- **Estado:** Aceptado con asuntos diferidos
- **Fecha:** 31 de julio de 2026

## Contexto

Claridez necesita esqueletos técnicos reproducibles para Django y React antes de iniciar la plataforma local o cualquier módulo funcional. La selección debe privilegiar soporte, seguridad, compatibilidad real en Windows y lockfiles verificables.

## Decisiones aceptadas

- Usar Python 3.13.14 con uv 0.12.0 y `uv.lock`.
- Usar Django 5.2.16 LTS, Django REST Framework 3.16.1 y Psycopg 3.3.4.
- Mantener PostgreSQL 17 como único motor objetivo, sin instalarlo ni conectarlo en esta iteración.
- Usar Node.js 24.18.1, npm 11.16.0 y workspaces npm con `package-lock.json` raíz.
- Usar React y React DOM 19.2.8 con parches idénticos.
- Usar TypeScript 6.0.3 y Vite 8.1.5: superaron React, Vitest, Testing Library, ESLint, tipos estrictos y build productivo.
- Usar Ruff, mypy con django-stubs, pytest, pytest-django, pytest-cov y coverage.py en Python.
- Usar ESLint, typescript-eslint, React Hooks, Prettier, Vitest, Testing Library, jsdom y cobertura V8 en frontend.
- Usar `npm run format`, `lint`, `typecheck`, `test`, `build` y `check` como fachada oficial desde la raíz.
- Mantener `audit` separado de `check` por su dependencia de servicios de red.
- Generar OpenAPI con drf-spectacular como artefacto temporal ignorado.

## Validaciones completadas

- mypy 1.19.1 y django-stubs 5.2.9 pasan en modo estricto sin desactivar controles importantes.
- TypeScript 6.0.3 y Vite 8.1.5 pasan lint, typecheck, Vitest con cobertura y build productivo bajo Node.js 24.18.1.
- drf-spectacular 0.30.0 genera y valida el esquema técnico con advertencias tratadas como errores.
- Los comandos bootstrap no abren una conexión a PostgreSQL.

## Aspectos provisionales

- La configuración de desarrollo permanece provisional hasta la Iteración 2; las comprobaciones usan una configuración técnica que no conecta a PostgreSQL.

## Asuntos diferidos

- El artefacto productivo del backend y la estrategia de despliegue.
- La versión reproducible e instalación real de PostgreSQL 17.
- La publicación del contrato OpenAPI y la generación del cliente TypeScript.
- Los umbrales de cobertura globales.
- CI, contenedores y pruebas E2E.

## Alternativas evaluadas

- Python 3.14 se descartó para esta base por menor madurez comprobada del conjunto Django/DRF.
- Django 6.0 se descartó porque Django 5.2 ofrece soporte LTS más prolongado.
- TypeScript 5.9 y Vite 7.3 permanecen como retroceso condicionado a una incompatibilidad reproducible.
- pnpm, Poetry y pip-tools son alternativas válidas, pero agregan complejidad que no aporta valor en la estructura actual.
- Empaquetar la API como wheel o sdist se descartó hasta definir el despliegue.
- Versionar un esquema OpenAPI vacío se descartó porque todavía no existe un contrato funcional que preservar.

## Consecuencias

- Los entornos se reconstruyen mediante `uv sync --locked` y `npm ci`.
- Las versiones directas y los gestores quedan fijados explícitamente.
- `build` de la API valida Django, importaciones, sintaxis y OpenAPI sin producir un paquete distribuible.
- Las actualizaciones del toolchain requieren repetir la matriz y actualizar este ADR o reemplazarlo si cambia la decisión central.
- Vitest utiliza el pool de threads para evitar el bloqueo reproducido al iniciar procesos worker en Windows.

## Evidencia

Los resultados observados de la matriz se registran en `../architecture/TOOLCHAIN_COMPATIBILITY.md`.
