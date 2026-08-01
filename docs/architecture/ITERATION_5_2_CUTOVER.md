# Cutover de la Iteración 5.2

**Estado:** Procedimiento operativo aprobado  
**Alcance:** primera aplicación de las migraciones de `claridez.operations`

## Invariante de apertura

No se admite despliegue gradual ni convivencia entre procesos 5.1 y 5.2. El balanceador, proxy o
mecanismo equivalente debe mantener el tráfico cerrado desde antes de detener 5.1 hasta que la
comprobación posterior devuelva `status=ok`. `/health` y `/ready` se consultan por la ruta interna;
una respuesta correcta no abre tráfico por sí misma.

## Secuencia obligatoria

1. Cerrar el tráfico de aplicación y comprobar desde fuera que ninguna solicitud llega a Django.
2. Detener todos los procesos web de Claridez, incluidas réplicas y procesos reiniciables.
3. Verificar en el gestor de procesos que la cantidad de instancias es cero. Como segunda evidencia,
   comprobar en `pg_stat_activity` que no quedan sesiones de `claridez_app`. La segunda comprobación
   no sustituye la primera porque un proceso antiguo puede estar activo sin una sesión abierta.
4. Ejecutar `npm run db:migrate` una sola vez con la versión nueva. La migración 0001 toma
   `LOCK TABLE commercial_reservation IN SHARE ROW EXCLUSIVE MODE` antes de clasificar datos. El
   lock espera a escritores anteriores y hace esperar a todo `INSERT`, `UPDATE` o `DELETE` posterior,
   mientras conserva las lecturas ordinarias. Preflight, esquema, backfill, validación y defensas
   internas se confirman en una sola transacción.
5. Ejecutar `npm run db:operations-cutover-check`. El comando verifica la cabeza 0002, cardinalidad,
   siete claves base exactas, transiciones requeridas, RLS forzado y el guardián transversal. Solo
   `status=ok` es un resultado admisible.
6. Iniciar exclusivamente la versión 5.2, todavía sin abrir tráfico.
7. Repetir `npm run db:operations-cutover-check` desde el artefacto iniciado y comprobar por la ruta
   interna `/health`, `/ready`, el identificador de versión desplegado y que no exista ninguna
   instancia 5.1.
8. Abrir tráfico solo cuando todas las evidencias anteriores sean satisfactorias.

El conteo de sesiones PostgreSQL se realiza con una cuenta operativa autorizada, sin copiar
consultas ni resultados con datos personales a tickets o logs.

## Regla de fallo

Si cualquier fase falla, no se abre ni se reabre la aplicación. Se detienen los procesos nuevos que
pudieran haberse iniciado, se conserva el tráfico cerrado y se investiga el punto de fallo. Un error
de la migración atómica revierte esquema y backfill; un error posterior no autoriza volver a ejecutar
5.1, porque esa versión no conoce el coordinador ni las nuevas defensas. La reversión de 0001/0002
solo es una prueba técnica sobre una base desechable, no un procedimiento de recuperación sobre
datos operativos reales.

## Evidencia mínima del corte

- hora de cierre y reapertura de tráfico;
- versión exacta detenida y versión exacta iniciada;
- evidencia de cero procesos antiguos y cero sesiones `claridez_app` antes de migrar;
- salida y código de retorno de migración;
- ambas salidas `status=ok` del postcheck;
- resultados internos de `/health` y `/ready`;
- aprobación humana para abrir tráfico.

No se registran nombres, teléfonos, notas comerciales ni contenidos del checklist en esta evidencia.
