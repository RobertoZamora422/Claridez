# Cutover de P8 — Agenda y reservas avanzadas

**Estado:** Procedimiento aprobado y ensayable  
**Alcance:** adopción de `Reservation` por `claridez.scheduling` y sustitución de la exclusión
temporal 5.1/P6

## Qué acredita este documento

Este procedimiento separa tres hechos distintos:

- el procedimiento documentado y sus pruebas automatizadas;
- el ensayo sobre una base PostgreSQL local y desechable con datos sintéticos;
- una futura ejecución en un entorno destino, que requiere autorización y evidencia propias.

La existencia de este documento o un ensayo local no afirma un cutover productivo, de staging ni de
ningún otro entorno destino.

## Invariante de apertura

No existe convivencia admitida entre procesos anteriores a P8 y procesos P8. El tráfico permanece
cerrado desde antes de detener la versión anterior hasta que migraciones, postcheck, smoke tests y
verificación de versión concluyan correctamente. `/health` y `/ready` no abren tráfico por sí solos.

La tabla física `commercial_reservation` conserva UUID y filas. No se copia ni se renombra. La
migración cambia la propiedad de estado Django, completa los datos derivables y sustituye
`commercial_reservation_no_overlap` por la única exclusión
`scheduling_allocation_no_overlap` dentro de la misma transacción de migración.

## Preflight de go/no-go

Antes de mutar un entorno destino se debe:

1. identificar versión origen y cabeza de migraciones;
2. verificar que 5.2 fue aplicado o que su procedimiento será compuesto en la misma ventana;
3. cerrar tráfico, detener todos los procesos web y comprobar cero sesiones `claridez_app`;
4. comprobar backup recuperable y punto de restauración/PITR mediante el procedimiento operativo
   del entorno;
5. rechazar reservas con tenant, solicitud, cotización aceptada, espacio, intervalo o zona horaria
   incoherentes;
6. rechazar cotizaciones compartidas sin una cadena explicable, más de una reserva vigente por
   solicitud, confirmaciones/preparaciones parciales o solapamientos que la nueva exclusión
   rechazaría;
7. registrar solo conteos e identificadores técnicos en la evidencia, nunca nombres, teléfonos,
   notas, snapshots comerciales ni checklists.

La migración vuelve a realizar el preflight bajo `LOCK TABLE commercial_reservation IN SHARE ROW
EXCLUSIVE MODE`; si una validación falla, la transacción completa se revierte.

## Secuencia obligatoria

1. Mantener tráfico cerrado y procesos anteriores detenidos.
2. Ejecutar una sola vez `npm run db:migrate` con el artefacto P8.
3. La migración adopta `Reservation` por estado, crea las tablas privadas, raíces, ceros históricos,
   asignaciones y guardianes, y conserva la tabla física existente.
4. Los holds provisionales ya vencidos se convierten en `expired` como transición real. Solo esos
   holds reciben `reservation_expired`; una reserva que ya era histórica/terminal recibe únicamente
   el snapshot observado y no una transición inventada.
5. Cada reserva observada recibe un `cutover_snapshot` con `source=cutover`; montaje, desmontaje y
   buffers se conservan en cero cuando no existe evidencia anterior.
6. Ejecutar `npm run db:operations-cutover-check` cuando el corte 5.2 forme parte de la misma
   ventana o no exista evidencia de que ya fue ejecutado en el destino.
7. Ejecutar `npm run db:scheduling-cutover-check`. Solo `status=ok` es admisible; el comando valida
   la cabeza de migración, cadena, evidencia comercial, equivalencia dominio/proyección,
   expiraciones, RLS/FORCE RLS, guardianes y exclusión temporal única.
8. Iniciar exclusivamente la versión P8, todavía sin abrir tráfico.
9. Repetir ambos postchecks aplicables desde el artefacto iniciado y ejecutar smoke tests internos
   de sesión, CSRF, organización activa, membresía, disponibilidad, confirmación y agenda.
10. Verificar `/health`, `/ready`, versión desplegada y ausencia de procesos anteriores.
11. Abrir tráfico solo con aprobación humana y toda la evidencia anterior satisfactoria.

## Rollback antes de tráfico

La reversión técnica inmediata se admite únicamente si todavía no hubo tráfico P8 ni se crearon
bloqueos, sucesoras, reservas con snapshots temporales no nulos o preparaciones `rescheduled`.
En ese caso, sobre una base desechable o bajo el procedimiento autorizado del destino:

1. mantener procesos detenidos y tráfico cerrado;
2. revertir primero privilegios y guardianes P8;
3. retirar la exclusión unificada y restaurar `commercial_reservation_no_overlap`;
4. restaurar los guardianes 5.2 y el estado Django propietario anterior;
5. verificar que UUID, filas y FK siguen presentes;
6. reaplicar P8 o recuperar el backup según la causa investigada.

Después de tráfico o de datos P8 no representables por P7, no se inventa un down-migration: se usa
el backup/PITR ensayado. Un error nunca autoriza abrir tráfico ni reiniciar silenciosamente una
versión anterior.

## Ensayo local desechable

El ensayo automatizado usa PostgreSQL real y `MigrationExecutor` para:

- instalar desde base vacía hasta HEAD;
- migrar desde los estados exactos posteriores a P6 y P7;
- preservar UUID y cantidad de filas de reservas provisionales, confirmadas, expiradas y
  canceladas, junto con preparaciones existentes;
- comprobar raíces, ceros históricos, `cutover_snapshot`, asignaciones y expiración real de holds
  vencidos;
- revertir inmediatamente antes de tráfico y reaplicar;
- provocar preflights inválidos y observar rollback atómico;
- componer el corte 5.2 y P8 cuando ambos estaban pendientes.

La salida del ensayo debe identificarse expresamente como local/desechable. No se reutiliza como
evidencia de un entorno futuro.

## Evidencia mínima de un futuro entorno destino

- versión exacta origen y destino, cabeza de migraciones y ventana;
- hora de cierre y reapertura, cero procesos antiguos y cero sesiones `claridez_app`;
- referencia del backup/PITR verificado;
- código de salida de migración y de cada postcheck;
- conteos pre/post sin datos personales;
- smoke tests, `/health`, `/ready` e identificador de versión;
- decisión humana de go/no-go.
