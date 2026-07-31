# Matriz de compatibilidad de toolchains

- **Iteración:** 1 — Toolchains reproducibles
- **Fecha de evaluación:** 31 de julio de 2026
- **Estado:** validada y aceptada

Este documento registra versiones exactas y evidencia observada. No define arquitectura funcional, despliegue ni configuración productiva.

## Matriz seleccionada para prueba

| Componente | Versión exacta | Condición |
|---|---:|---|
| Python | 3.13.14 | Línea 3.13 aprobada |
| uv | 0.12.0 | Gestor Python fijado |
| Django | 5.2.16 | Último parche estable de 5.2 LTS al evaluar |
| Django REST Framework | 3.16.1 | Último parche estable de 3.16 al evaluar |
| drf-spectacular | 0.30.0 | Candidato compatible para OpenAPI |
| Psycopg | 3.3.4 | Driver PostgreSQL |
| pydantic-settings | 2.14.2 | Configuración local tipada y validada; añadido en la Iteración 2 |
| PostgreSQL | 17.10 | Imagen local `17.10-bookworm` fijada por digest en la Iteración 2 |
| Node.js | 24.18.1 | LTS Krypton |
| npm | 11.16.0 | Versión incluida con Node.js seleccionado |
| React | 19.2.8 | Mismo parche que React DOM |
| React DOM | 19.2.8 | Mismo parche que React |
| TypeScript | 6.0.3 | Primera línea exigida para validación |
| Vite | 8.1.5 | Primera línea exigida para validación |
| Vitest | 4.1.10 | Acepta Vite 8 y Node 24 |
| ESLint | 10.8.0 | Aceptado por typescript-eslint y plugins seleccionados |
| typescript-eslint | 8.65.0 | Acepta TypeScript menor que 6.1 y ESLint 10 |

No se utilizan versiones preliminares ni etiquetas flotantes. Los parches exactos se declaran en los manifiestos y lockfiles.

## Dependencias directas

### API en tiempo de ejecución

- Django: framework del monolito modular.
- Django REST Framework: API REST JSON.
- drf-spectacular: generación y validación OpenAPI.
- Psycopg con binarios: driver PostgreSQL reproducible en Windows durante esta etapa.
- pydantic-settings: perfiles locales tipados, secretos protegidos y fallo temprano de configuración.

### API de desarrollo

- Ruff: formato y lint.
- mypy y django-stubs: tipos estrictos compatibles con Django 5.2.
- pytest y pytest-django: pruebas técnicas.
- coverage.py y pytest-cov: cobertura sin umbral global inicial.
- pip-audit: auditoría separada y dependiente de red.

### Web en tiempo de ejecución

- React y React DOM: runtime de interfaz.

### Web de desarrollo

- TypeScript, Vite y plugin React: tipos y build.
- ESLint, typescript-eslint, React Hooks, React Refresh y globals: lint.
- Prettier: formato.
- Vitest, Testing Library, jest-dom y jsdom: pruebas técnicas.
- Cobertura V8: reporte de cobertura.
- Tipos de Node, React y React DOM: declaraciones estáticas.

## Resultado de la matriz

| Validación | Resultado observado |
|---|---|
| `uv --directory apps/api sync --locked` | Correcto con Python 3.13.14; 60 paquetes instalados |
| `npm ci` | Correcto; 251 paquetes instalados y lockfile sin cambios |
| `format:check` | Correcto; Ruff confirmó 11 archivos y Prettier confirmó el workspace web |
| `lint` | Correcto; Ruff y ESLint 10 sin errores ni advertencias |
| `typecheck` | Correcto; mypy estricto en 10 archivos y TypeScript 6.0.3 sin errores |
| `test` | Correcto; 1 prueba backend y 1 prueba frontend |
| `build` | Correcto; Django check, compileall, OpenAPI y Vite 8.1.5 |
| `check` | Correcto de extremo a extremo |
| `pip-audit` | 0 vulnerabilidades conocidas |
| `npm audit` | 0 vulnerabilidades conocidas |

La reinstalación con uv y `npm ci` conservó sin cambios los SHA-256 de `uv.lock` y `package-lock.json`.

## Compatibilidad confirmada

TypeScript 6.0.3 y Vite 8.1.5 funcionan con React 19.2.8, Vitest 4.1.10, Testing Library, ESLint 10.8.0, typescript-eslint 8.65.0 y Node.js 24.18.1. No fue necesario retroceder a TypeScript 5.9 ni Vite 7.3.

mypy 1.19.1 y django-stubs 5.2.9 funcionan con Django 5.2.16 en modo estricto. Se añadió `src` a la ruta de mypy para que el plugin importe la configuración técnica; no se desactivó ninguna comprobación estricta.

## Ajustes observados durante la validación

- Las configuraciones tipadas de typescript-eslint se limitaron a `.ts` y `.tsx`; el archivo JavaScript de ESLint conserva reglas JavaScript sin intentar usar información de un proyecto TypeScript inexistente.
- jest-dom se referencia mediante su integración específica para Vitest y las primitivas de prueba se importan explícitamente.
- El pool predeterminado de procesos de Vitest agotó el tiempo al iniciar un worker en Windows. El pool de threads ejecutó correctamente la misma prueba y quedó fijado.
- `manage.py` añade el directorio `src` a su ruta porque la API no se empaqueta en esta iteración.

## OpenAPI

`apps/api/openapi-schema.yaml` es un artefacto temporal ignorado. Se regenera y valida durante `build` y `check`; no debe editarse ni interpretarse aún como contrato funcional versionado. La decisión de publicar el contrato se retomará cuando existan endpoints aprobados.

## Extensión validada en la Iteración 2

`pydantic-settings` 2.14.2 resolvió de forma compatible con Python 3.13.14, Django 5.2.16, mypy estricto y los lockfiles existentes. Su resolución exacta incorpora Pydantic 2.13.4, pydantic-core 2.46.4, python-dotenv 1.2.2, annotated-types 0.8.0 y typing-inspection 0.4.2.

PostgreSQL 17.10 fue comprobado mediante la imagen y digest registrados en [LOCAL_PLATFORM.md](LOCAL_PLATFORM.md). La aplicación se conectó con Psycopg 3.3.4, ejecutó sesiones UTC y pruebas reales sin introducir SQLite.

## Límites

- La afirmación original de que PostgreSQL no se conectaba corresponde exclusivamente a la Iteración 1. La Iteración 2 añade su plataforma local y suite de integración.
- No se producen wheel, sdist ni artefactos productivos de backend.
- La cobertura observada fue 62% en backend y 100% sobre el único componente técnico frontend incluido. Informa el alcance del esqueleto, pero no es un objetivo de calidad definitivo.
- Las auditorías dependen del estado del servicio externo al momento de ejecutarse.
