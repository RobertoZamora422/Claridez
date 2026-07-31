# AGENTS.md

## 1. Función y alcance

Este archivo establece las reglas obligatorias para cualquier persona o agente automatizado que trabaje en Claridez. Aplica a todo el repositorio, salvo que un archivo `AGENTS.md` más específico añada reglas compatibles para una subcarpeta.

`AGENTS.md` no sustituye la documentación de producto, los ADR, la guía de contribución ni la política de seguridad. Su función es convertir sus principios esenciales en reglas operativas para cada cambio.

## 2. Identidad e independencia

- El producto se llama **Claridez**.
- Claridez es un proyecto nuevo y completamente independiente de RFM Core.
- Está prohibido copiar de RFM Core código, migraciones, estructura interna, historial Git, configuración, secretos, datos o decisiones no verificadas.
- Una similitud de tecnología no autoriza reutilización de implementación.
- El repositorio es privado y el software es propietario.
- No se debe crear una licencia de código abierto ni inventar términos legales.

## 3. Fuentes de verdad

Las fuentes se interpretan según su ámbito:

1. Los ADR aceptados gobiernan las decisiones arquitectónicas que registran.
2. `docs/product/PRODUCT_BASELINE.md` registra la línea base del producto v0.1, pero no es una especificación funcional completa.
3. `docs/brand/CLARIDEZ_FUNDAMENTOS_DE_MARCA.md` es la fuente principal para propósito, posicionamiento, personalidad y lenguaje de marca.
4. `docs/brand/CLARIDEZ_DIRECCION_VISUAL_OFICIAL.md` prevalece exclusivamente en decisiones visuales.
5. Una especificación funcional aprobada para una iteración futura gobernará el flujo que describa sin modificar silenciosamente estas fuentes.

Si dos fuentes parecen contradecirse fuera de esta jerarquía, se debe detener la decisión afectada y documentar el conflicto.

## 4. Arquitectura aprobada

- Monorepo.
- Monolito modular.
- Backend: Django y Django REST Framework.
- Frontend: React, TypeScript estricto y Vite.
- PostgreSQL en desarrollo, CI, staging y producción.
- API REST JSON versionada bajo `/api/v1`.
- Contrato OpenAPI y futuro cliente TypeScript generado.
- No se utilizarán microservicios.

La matriz concreta se registra en `docs/architecture/TOOLCHAIN_COMPATIBILITY.md`. Los manifiestos y lockfiles son la fuente ejecutable de versiones; una actualización requiere verificación y documentación deliberadas.

## 5. Invariantes multiempresa

- La arquitectura multiempresa existe desde el inicio.
- Todo dato privado debe pertenecer a una organización.
- Las excepciones globales deben ser explícitas, mínimas y justificadas.
- Un usuario puede pertenecer a varias organizaciones mediante membresías.
- Ningún identificador de organización enviado por un cliente se considera confiable sin validar la membresía y el contexto activo.
- Consultas, escrituras, relaciones, archivos, cachés y futuros trabajos asíncronos deberán respetar el contexto organizacional.
- Los accesos cruzados deben probarse de forma negativa con al menos dos organizaciones.
- No se debe afirmar que RLS está adoptado. Su conveniencia y funcionamiento con Django requieren el spike aprobado de la Iteración 3.

## 6. Perfiles iniciales provisionales

Los siguientes nombres y propósitos generales están aprobados de forma provisional:

- `propietario`: referente principal de la organización y de su control general.
- `administrador`: apoyo en la administración cotidiana de la organización.
- `comercial`: trabajo relacionado con la gestión comercial.
- `operaciones`: trabajo relacionado con la preparación y ejecución operativa.
- `finanzas`: trabajo relacionado con el seguimiento económico y financiero.

Estos perfiles no constituyen una matriz definitiva de permisos. Está prohibido inferir capacidades, jerarquías, excepciones o accesos concretos sin una especificación posterior aprobada.

## 7. Alcance del producto

- Mercado inicial: Ecuador.
- Zona horaria inicial: `America/Guayaquil`.
- Moneda inicial: USD.
- Moneda y zona horaria deberán pertenecer a la configuración de cada organización.
- Claridez no ofrecerá contabilidad formal ni facturación electrónica en la V1.
- El Modelo de Conversión y los dominios propios son parte de la visión futura, no el primer módulo funcional.
- No se implementará un constructor web libre.
- No se deben inventar procesos, entidades, estados, cálculos o reglas de negocio aún no aprobados.

## 8. Alcance técnico establecido

La Iteración 1 incorpora únicamente esqueletos técnicos en `apps/api` y `apps/web`, dependencias fijadas, lockfiles y comandos reproducibles. Hasta que exista una nueva instrucción explícita, no se deben crear:

- Aplicaciones funcionales, modelos, migraciones o endpoints de negocio.
- Organizaciones, membresías, usuarios del dominio ni configuración multiempresa productiva.
- Workflows de CI.
- Contenedores o infraestructura.
- Integraciones o proveedores externos.
- Cliente TypeScript generado.

## 9. Dependencias y herramientas

- Toda dependencia futura necesita una necesidad concreta y compatibilidad comprobada.
- No se añadirán colas, Redis, brokers, Celery, Dramatiq ni workers hasta que exista un proceso asíncrono real.
- El patrón outbox permanece diferido como candidato; no es código obligatorio.
- Docker se utilizará cuando aporte reproducibilidad, especialmente para PostgreSQL, pero no será requisito para cada comando local en Windows.
- No se implementará una plataforma completa de OpenTelemetry de forma anticipada.

## 10. Seguridad y datos

- Nunca se versionan secretos, credenciales, tokens, llaves privadas ni datos reales de clientes.
- Los ejemplos deben ser sintéticos y no identificables.
- Las vulnerabilidades se reportan según `SECURITY.md`.
- OWASP ASVS es una referencia y fuente progresiva de checklists, no una certificación ya alcanzada.
- La autorización debe denegar por defecto cuando una decisión no esté definida.
- Los logs futuros no deben contener secretos ni datos sensibles innecesarios.
- Las operaciones financieras futuras deberán evitar números de punto flotante y preservar trazabilidad; sus reglas concretas requieren especificación.

## 11. Cambios arquitectónicos y ADR

Se requiere un ADR cuando un cambio:

- Altera una decisión aprobada.
- Introduce un componente transversal o proveedor.
- Cambia el aislamiento multiempresa.
- Introduce una dependencia operativa importante.
- Establece una convención difícil de revertir.

Los ADR deben separar expresamente decisiones aceptadas, aspectos provisionales, asuntos diferidos y validaciones o spikes pendientes. No deben presentar una hipótesis como decisión definitiva.

## 12. Marca e interfaz

- La dirección visual oficial prevalece solo en materias visuales.
- Los fundamentos de marca gobiernan propósito, posicionamiento, personalidad y lenguaje.
- Las copias controladas en `docs/brand/` no se editan silenciosamente.
- Cada cambio visual futuro debe conservar claridad, jerarquía, accesibilidad y el concepto de centro de control claro.

## 13. Forma de trabajo

Antes de cambiar código o documentación:

1. Revisar el estado actual y las fuentes aplicables.
2. Identificar decisiones aprobadas y pendientes.
3. Mantener el cambio dentro de la iteración autorizada.
4. Preservar trabajo existente no relacionado.

Al finalizar:

1. Enumerar archivos modificados.
2. Informar comprobaciones ejecutadas y resultados observados.
3. Distinguir pruebas dirigidas de suites completas.
4. Declarar cualquier validación omitida o incompleta.
5. No realizar remotos, despliegues ni acciones externas sin autorización explícita.
6. Los commits de Claridez son ejecutados exclusivamente por el propietario; los agentes automatizados no crean commits.

### Comandos oficiales

Desde la raíz del repositorio:

- `npm run format`: aplica formato; modifica archivos.
- `npm run format:check`: comprueba formato sin modificar.
- `npm run lint`: ejecuta lint de Python y TypeScript.
- `npm run typecheck`: ejecuta mypy/django-stubs y TypeScript estricto.
- `npm test`: ejecuta pruebas y genera cobertura.
- `npm run build`: valida Django, sintaxis, OpenAPI y el build de Vite.
- `npm run check`: ejecuta la puerta local completa sin auditorías de red.
- `npm run audit`: audita dependencias mediante servicios externos.

Las instalaciones reproducibles son `uv --directory apps/api sync --locked` y `npm ci`.

## 14. Criterio general de finalización

Un cambio está terminado cuando cumple su alcance aprobado, respeta las fuentes de verdad, conserva los invariantes multiempresa, no introduce secretos, supera las comprobaciones pertinentes y deja documentación coherente con lo realmente implementado.

Los comandos oficiales deben completar correctamente y no se deben reducir controles importantes solo para hacerlos pasar. Las limitaciones reales de una herramienta se documentan antes de cambiarla o sustituirla.
