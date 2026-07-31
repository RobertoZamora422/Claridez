# Modelo de amenazas reducido del spike de tenancy

- **Fecha:** 2026-07-31
- **Alcance:** evidencia experimental, no control productivo aprobado

## Activos y límite de confianza

El activo es cualquier dato privado perteneciente a una organización. El límite de confianza es el
contexto organizacional que la aplicación haya autenticado, autorizado y validado antes de acceder
a datos. Un UUID enviado por cliente, incluido en una URL o conocido por un actor nunca constituye
esa validación.

RLS recibe el GUC `claridez.organization_id`; no conoce usuarios, membresías, roles funcionales ni
el motivo de acceso.

## Amenazas y controles evaluados

| Amenaza | Control de aplicación | Defensa RLS | Riesgo restante |
|---|---|---|---|
| IDOR o UUID filtrado | búsqueda filtrada y error indistinguible | `USING` oculta filas ajenas | autorización previa obligatoria |
| consulta ORM sin filtro | servicio y manager soportado | fail-closed por fila | tablas sin RLS siguen expuestas |
| manager base, `raw()` o SQL directo | revisión y pruebas | RLS también cubre SQL directo | propietario o rol privilegiado requiere gobierno |
| bulk sin servicio | validación previa | `WITH CHECK` rechaza escritura cruzada | manejo correcto de errores transaccionales |
| relación cruzada | validación Django | no basta por sí sola | FK compuesta en base de datos |
| job o comando sin tenant | scope explícito obligatorio | cero filas y escrituras rechazadas | jobs globales requieren diseño separado |
| contaminación de conexión | `ContextVar` y scope | `SET LOCAL` limitado a transacción | contexto de sesión persistente es inseguro |
| acceso administrativo | caso de uso explícito | `FORCE RLS` puede incluir al propietario | soporte excepcional aún no diseñado |
| importación/exportación | servicio tenant-aware | políticas por fila | archivos, colas y objetos externos requieren controles propios |
| logs con datos ajenos | redacción y mínimos datos | RLS no protege logs ya emitidos | política de logging productiva pendiente |
| migración de datos | migrador y procedimiento explícito | propietario evita RLS salvo `FORCE` | cada migración debe declarar scope y auditoría |
| archivos asociados | clave y ruta tenant-aware | RLS solo protege metadatos PostgreSQL | aislamiento del almacenamiento pendiente |

## Fault injections relevantes

- Los bypasses de aplicación expusieron conteos de filas de ambas organizaciones y permitieron
  escrituras cruzadas por bulk y SQL directo.
- Un contexto PostgreSQL a nivel de sesión contaminó el consumidor siguiente de la misma conexión.
- Un UUID válido de otra organización permitió al rol de aplicación ver esa organización bajo RLS.
  Esto es comportamiento correcto de la política recibida y prueba que RLS no autoriza membresía.
- UUID ausente, vacío o malformado produjo ausencia segura de tenant.

## Requisitos para una implementación futura

- Validar autenticación, membresía, organización activa y permiso antes de abrir `tenant_scope`.
- Mantener consultas y servicios tenant-aware aunque exista RLS.
- Abrir una transacción exterior explícita antes de `SET LOCAL`.
- Rechazar cambio de tenant dentro del scope.
- Exigir FK y unicidades compuestas en PostgreSQL para relaciones privadas.
- No conceder `BYPASSRLS` a roles normales, workers o soporte.
- Diseñar acceso excepcional de soporte con autorización reforzada, razón, alcance temporal y
  auditoría; no usar un tenant global.
- Aplicar la misma frontera a archivos, exportaciones, caches, logs y futuros procesos asíncronos.
