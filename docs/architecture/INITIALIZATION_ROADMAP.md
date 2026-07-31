# Roadmap técnico de inicialización

- **Estado de la Iteración 0:** completada documentalmente el 31 de julio de 2026
- **Alcance:** preparación técnica hasta habilitar el primer flujo vertical

Este roadmap ordena la inicialización del producto. No es un cronograma comercial ni una especificación funcional.

## Principios de ejecución

- Cada iteración debe ser pequeña, verificable y tener un criterio de salida.
- No se prolongará la preparación de infraestructura indefinidamente.
- No se adelantarán componentes cuya necesidad todavía no exista.
- Una iteración posterior no comienza hasta resolver las decisiones que la bloquean.
- No se realizarán despliegues o acciones externas sin autorización explícita.

## Iteración 0 — Gobierno documental

### Alcance

- Inicializar Git local sin historial ajeno.
- Crear documentos raíz de gobierno.
- Crear estructura y ADR iniciales.
- Incorporar copias controladas de marca.
- Registrar la línea base del producto v0.1 y la jerarquía documental.

### Exclusiones

- Dependencias.
- Código de aplicación.
- Entidades o migraciones.
- Workflows, remotos, commits y proveedores externos.

### Criterio de salida

- Árbol documental completo.
- UTF-8 y LF verificados.
- Enlaces relativos válidos.
- Hashes de marca coincidentes.
- Ausencia básica de secretos.
- Estado Git local informado y sin commit.

## Iteración 1 — Toolchains

### Alcance

- Proponer y verificar una matriz de versiones compatibles.
- Crear esqueletos mínimos de `apps/api` y `apps/web`.
- Activar TypeScript estricto.
- Crear lockfiles.
- Añadir comandos oficiales de formato, lint, tipos, pruebas y build.

### Restricciones

- No elegir versiones solamente por ser las más recientes.
- No crear entidades del dominio.

### Criterio de salida

- Compatibilidad documentada.
- Instalación reproducible.
- Backend y frontend mínimos construyen y ejecutan sus pruebas técnicas.

## Iteración 2 — Plataforma local

### Alcance

- PostgreSQL reproducible.
- Configuración validada y ambientes separados.
- Secretos fuera de Git.
- Endpoints técnicos de salud.
- CI básico.

### Restricciones

- Sin despliegue externo.
- Docker se usará cuando aporte reproducibilidad, sin obligar a ejecutar cada comando local dentro de un contenedor en Windows.

### Criterio de salida

- Entorno local reconstruible.
- PostgreSQL real utilizado por pruebas de integración.
- Configuración inválida falla de forma explícita.
- CI ejecuta las comprobaciones básicas aprobadas.

## Iteración 3 — Spike de tenancy

### Alcance

- Comparar aislamiento de aplicación frente a aplicación más PostgreSQL RLS.
- Usar al menos dos organizaciones.
- Probar lecturas y escrituras cruzadas.
- Probar relaciones tenant-aware.
- Probar pooling, transacciones, migraciones, comandos, tareas y conexiones reutilizadas.
- Documentar resultados y recomendación mediante ADR.

### Restricciones

- El código del spike no se convierte automáticamente en código productivo.
- No se adopta RLS antes de observar evidencia suficiente.

### Criterio de salida

- Resultados reproducibles.
- Riesgos y limitaciones documentados.
- Estrategia de aislamiento aprobada antes de modelar datos privados productivos.

## Iteración 4 — Identidad, organizaciones y autorización

### Condición de entrada

- Estrategias de identidad y tenancy aprobadas.

### Alcance

- Implementar la opción de identidad seleccionada.
- Establecer organizaciones y membresías.
- Incorporar los perfiles provisionales sin inventar una matriz definitiva.
- Aplicar aislamiento y denegación por defecto.

### Criterio de salida

- Identidad y recuperación evaluadas según la opción elegida.
- Cambio de contexto organizacional sin mezcla de datos.
- Accesos cruzados rechazados mediante pruebas.
- Autorización mínima respaldada por una especificación aprobada.

## Iteración 5 — Primer flujo vertical funcional

### Condición de entrada

- Repositorio, toolchains, PostgreSQL, tenancy, identidad, organizaciones y autorización establecidos.
- Especificación funcional separada y aprobada.

### Alcance

El flujo se definirá posteriormente. Debe atravesar las capas necesarias de forma vertical y entregar valor verificable sin intentar construir todos los módulos del producto.

### Criterio de salida

Será definido por la especificación funcional correspondiente, incluyendo reglas, estados, permisos, pruebas y criterios de aceptación.

## Decisiones transversales diferidas

- Infraestructura asíncrona y patrón outbox: al primer proceso asíncrono real.
- Métricas y trazas distribuidas: cuando los logs y el seguimiento de errores no sean suficientes.
- Proveedores de staging y producción: antes de preparar esos ambientes.
- Modelo de Conversión y dominios propios: después de validar los flujos internos prioritarios.
