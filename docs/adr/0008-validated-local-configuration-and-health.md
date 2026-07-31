# ADR 0008 — Configuración local validada y endpoints técnicos

- **Estado:** Aceptado con asuntos diferidos
- **Fecha:** 31 de julio de 2026

## Contexto

Las credenciales, puertos y perfiles incorrectos deben fallar antes de iniciar Django. La aplicación necesita señales técnicas mínimas que distingan un proceso vivo de una instancia preparada para atender solicitudes, sin filtrar información del entorno.

## Decisiones aceptadas

- Usar `pydantic-settings` 2.14.2 para cargar y validar la configuración local desde variables de entorno y el `.env` ignorado.
- Versionar `.env.example` sin secretos y mantener `.env` fuera de Git.
- Separar modelos de configuración para ejecución, migración, pruebas y bootstrap, de modo que Django normal no cargue credenciales administrativas o de migración.
- Fallar de inmediato ante variables ausentes, perfiles incorrectos, puertos inválidos, secretos demasiado cortos, nombres no autorizados u hosts que no sean loopback.
- Sanitizar errores de validación: pueden mencionar campos y tipos de error, pero no valores recibidos.
- Configurar Django con `TIME_ZONE = "America/Guayaquil"`, `USE_TZ = True` y `LANGUAGE_CODE = "es-ec"`; PostgreSQL persiste y ejecuta sesiones en UTC.
- Mantener CORS deshabilitado y permitir solamente hosts locales conocidos en desarrollo.
- Emitir logs técnicos JSON a salida estándar con evento, nivel, logger y tiempo UTC; no incluir configuración ni trazas de excepción por defecto.
- Exponer únicamente `GET` y `HEAD` en `/health` y `/ready`.
- Hacer que `/health` responda `200`, `{"status":"ok"}` y `Cache-Control: no-store` sin consultar PostgreSQL.
- Hacer que `/ready` ejecute una consulta mínima `SELECT 1`, responda `200` si PostgreSQL está disponible y `503` en fallos de conexión, credenciales o timeout.
- Mantener las respuestas de readiness genéricas, sin host, puerto, base, usuario, versión, SQL, excepción o latencia.
- No comprobar migraciones en cada solicitud de readiness.

## Alternativas evaluadas

- Leer `os.environ` directamente tiene menos dependencias, pero dispersa conversiones, valores y errores; se descartó para esta configuración transversal.
- `django-environ` y `environs` son alternativas maduras. `pydantic-settings` fue elegido por sus modelos tipados, validadores y representación protegida de secretos.
- Un único modelo con todas las variables simplificaría el código, pero cargaría credenciales que el proceso normal no necesita; se descartó.
- Hacer que `/health` consulte la base mezclaría vida y disponibilidad; se descartó.
- Comprobar migraciones en `/ready` añadiría costo y acoplamiento a cada solicitud; las migraciones se verifican mediante comandos separados.

## Aspectos provisionales

- Los límites de timeout locales podrán ajustarse con evidencia operativa.
- La política de logs es una base mínima; todavía no existe correlación completa de solicitudes ni un proveedor de seguimiento de errores.

## Asuntos diferidos

- Configuraciones concretas de staging y producción, que deberán usar secretos inyectados y no archivos `.env` desplegados.
- Dominios, hosts y políticas CORS productivos.
- Métricas, trazas, alertas y comprobaciones sintéticas.
- Endpoints funcionales bajo `/api/v1`.

## Consecuencias

- Los comandos Django locales requieren un `.env` válido incluso cuando una comprobación no abre conexión.
- Las pruebas rápidas pueden validar configuración y endpoints sin base; la suite de integración comprueba PostgreSQL real por separado.
- El contrato técnico no crea aplicaciones, modelos, migraciones ni entidades funcionales.
