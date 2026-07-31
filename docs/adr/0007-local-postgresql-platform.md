# ADR 0007 — Plataforma PostgreSQL local reproducible

- **Estado:** Aceptado con asuntos diferidos
- **Fecha:** 31 de julio de 2026

## Contexto

Claridez necesita usar PostgreSQL real desde desarrollo y pruebas sin obligar a ejecutar Django o React dentro de contenedores en Windows. El entorno local también debe anticipar la separación entre migraciones, ejecución y pruebas sin adoptar todavía RLS ni una topología productiva.

## Decisiones aceptadas

- Ejecutar Django y React/Vite nativamente en Windows.
- Contenerizar únicamente PostgreSQL mediante Docker Desktop y Docker Compose.
- Usar la imagen oficial `postgres:17.10-bookworm` fijada al digest del índice OCI `sha256:4f736ae292687621d4dbe0d499ffd024a36bd2ee7d8ca6f2ccd4c800f047b394`.
- Fijar `platform: linux/amd64`. El manifiesto correspondiente a esa arquitectura fue `sha256:67870dc097790edf2bd6726658db995dcc830f799d41bb2b78ef07c9a2d5f010` al verificarlo.
- Publicar el puerto interno `5432` exclusivamente como `127.0.0.1:${CLARIDEZ_DB_PORT}`, con `55432` como valor local predeterminado.
- Persistir el clúster en el volumen nombrado `claridez_postgres17_data`.
- Inicializar con UTF-8 y ejecutar servidor y sesiones en UTC.
- Identificar el clúster local mediante `cluster_name=claridez-local` para reforzar las protecciones del reset.
- Usar una política de reinicio limitada a `on-failure:3`, apropiada para un servicio de desarrollo iniciado de forma explícita.
- Reservar `postgres` para bootstrap local explícito y crear los roles separados `claridez_migrator`, `claridez_app` y `claridez_test_runner`.
- Ejecutar migraciones solo con `claridez_migrator`, Django normal solo con `claridez_app` y pruebas solo con `claridez_test_runner`.
- Ejecutar pruebas de integración contra PostgreSQL real. El rol de pruebas crea y destruye exclusivamente `claridez_test`.

## Privilegios aceptados

- Ningún rol de Claridez es superusuario ni posee `CREATEROLE`, `REPLICATION` o `BYPASSRLS`.
- Solo `claridez_test_runner` posee `CREATEDB`, limitado conceptualmente al clúster local por la configuración y los comandos de esta plataforma.
- `claridez_migrator` es propietario de `claridez_local` y del esquema `public`; puede ejecutar DDL y migraciones.
- `claridez_app` recibe `CONNECT`, `USAGE` del esquema y únicamente `SELECT`, `INSERT`, `UPDATE` y `DELETE` sobre tablas aplicables ya creadas. Recibe los permisos necesarios sobre secuencias, pero no `CREATE`, DDL, propiedad de tablas ni acceso a `django_migrations`.
- El bootstrap revoca privilegios de `PUBLIC` sobre la base y el esquema locales. Después de cada migración se reconcilian los permisos de objetos mediante el comando de preparación.

## Alternativas evaluadas

### PostgreSQL instalado directamente en Windows

Reduce el consumo de Docker y puede ofrecer una experiencia nativa sencilla, pero aumenta la variación entre instalaciones, servicios, rutas, locales y procedimientos de reinicio. No fue seleccionado para la base reproducible.

### Docker Desktop y Docker Compose

Ofrece una definición versionada, aislamiento, volumen administrado y una topología más cercana a una futura CI. Su costo es el consumo de Docker Desktop y la dependencia de virtualización. Fue seleccionado solo para PostgreSQL.

### PostgreSQL en una distribución WSL

Puede ser útil para equipos que ya trabajan dentro de WSL, pero introduce una segunda capa de administración y diferencias de red y archivos frente a los comandos nativos de PowerShell. No aporta una ventaja suficiente para el flujo aprobado.

### Base administrada externa

Puede corresponder a staging o producción futuros. No fue seleccionada para desarrollo porque agrega red, costo, dependencia externa y riesgo sobre datos remotos.

## Aspectos provisionales

- El puerto `55432` es un valor local predeterminado configurable y validado.
- Los permisos DML se reconcilian después de migrar. La política podrá estrecharse cuando existan módulos y tablas reales.
- El uso de `linux/amd64` refleja la arquitectura verificada en esta implementación; otra arquitectura requiere repetir la comprobación del manifiesto y la matriz.

## Asuntos diferidos

- Imagen y artefacto productivos de PostgreSQL.
- Proveedores y topologías de CI, staging y producción.
- Procedimientos `db:dump` y `db:restore`, hasta que existan datos y una política real de recuperación.
- Pooling, alta disponibilidad, réplicas y mantenimiento operativo remoto.
- Políticas RLS, pendientes del spike de la Iteración 3.

## Consecuencias

- Docker no es requisito para ejecutar herramientas frontend ni backend que no necesiten base de datos.
- Los comandos que dependen de PostgreSQL requieren Docker Desktop activo y un `.env` local válido.
- Detener o recrear el contenedor no elimina el volumen. El reset normal tampoco elimina roles, clúster ni volumen.
- Las credenciales locales son sintéticas, generadas y no versionadas; no son apropiadas para ambientes remotos.

## Evidencia y actualización controlada

El tag, los manifiestos, las versiones observadas y las pruebas se registran en [la plataforma local](../architecture/LOCAL_PLATFORM.md). Cualquier actualización debe volver a comprobar el tag oficial, el índice OCI, la arquitectura, Compose, persistencia, privilegios, migraciones, endpoints y suites antes de sustituir el digest.
