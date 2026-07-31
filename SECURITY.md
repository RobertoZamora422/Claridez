# Política de seguridad

## Estado

Claridez se encuentra en desarrollo inicial y todavía no tiene una versión comercial publicada. Esta política evolucionará junto con el producto y su modelo de amenazas.

OWASP ASVS se utilizará progresivamente como referencia y fuente de checklists. Este repositorio no declara todavía una verificación formal completa ni una certificación de cumplimiento.

## Reporte de vulnerabilidades

Las vulnerabilidades deben comunicarse **privadamente al propietario del repositorio**.

No se deben reportar vulnerabilidades mediante issues públicos, discusiones públicas ni otros canales visibles. Todavía no existe un correo o canal específico configurado y este documento no promete tiempos de respuesta.

Al reportar un problema de forma privada, incluye únicamente la información necesaria para reproducirlo y evaluar su impacto. No extraigas, copies ni compartas datos de terceros.

## Secretos y credenciales

- No se permiten secretos, contraseñas, tokens, cookies, llaves privadas ni credenciales en Git.
- Los archivos locales de ambiente deben permanecer ignorados.
- Los ejemplos documentales deben usar valores ficticios claramente identificables.
- Una credencial expuesta debe considerarse comprometida y rotarse; eliminarla del último commit no basta para protegerla.
- No se deben registrar secretos en logs, capturas, artefactos de CI ni mensajes de error.

## Datos y privacidad

- No se utilizarán datos reales de organizaciones o personas en desarrollo, CI, demostraciones o pruebas.
- Todo dato privado futuro deberá estar aislado por organización.
- Logs y telemetría deberán minimizar datos personales y financieros.
- Las políticas de retención, exportación y eliminación todavía requieren definición antes del lanzamiento comercial.

## Dependencias y cadena de suministro

Las dependencias futuras deberán fijarse mediante lockfiles, revisarse por mantenimiento y vulnerabilidades, y actualizarse con un proceso verificable. Los workflows y acciones externas, cuando se autoricen, deberán usar permisos mínimos y referencias inmutables cuando sea posible.

## Alcance futuro de seguridad

Antes del lanzamiento comercial deberán existir, como mínimo:

- Modelo de amenazas multiempresa revisado.
- Pruebas negativas de aislamiento entre organizaciones.
- Gestión formal de secretos por ambiente.
- Proceso de actualización de dependencias.
- Registro de auditoría para operaciones sensibles.
- Estrategia de copias de seguridad y restauración comprobada.
- Revisión progresiva de los controles ASVS aplicables.

Estas condiciones son objetivos de preparación, no afirmaciones de capacidades ya implementadas.
