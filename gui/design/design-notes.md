# Notas de diseño — interfaz de loudsync

Derivado de `direccion-de-arte.md`. Maquetas de la ronda 1 en `mockups-ronda-1/`
(proyecto Stitch "loudsync desktop — ronda 1", 10926243221490632904).

**Dirección elegida: A, "estado + ficha"** (operador, 27-09-2026). B (vigía centrado)
escondía los datos que respaldan el estado. C (estado + actividad) exigía conteos por
corrida que hoy no se conocen. La lista de corridas de C pasa a la página Activity.

## Correcciones sobre las maquetas

Las maquetas fijan distribución, jerarquía y texto. Donde contradicen la dirección de
arte, manda la dirección de arte:

| Maqueta | Qué muestra | Qué se construye | Por qué |
|---|---|---|---|
| Todas | Fuente Source Sans 3, colores de superficie propios | Fuente y superficies del tema GTK | Paleta: solo el estado lleva color propio |
| A-status | "812 files" | Sin conteo de archivos | Certera: el motor no lo sabe |
| A-conflicts | Botones "Keep kept version" / "Keep other version" | "Keep current" / "Keep other copy", con líneas "Current: …" y "Other copy: …" | Voz: "kept version" es jerga, y los botones nombran lo mismo que las líneas |
| A-conflicts | Tarjetas separadas por archivo | Filas de un `Gtk.ListBox` con marco | Widgets estándar |
| A-settings | "Keep local copies…" con enlace "Open versions" | Botón plano "Open versions" | GTK3 no tiene enlaces en filas sin `Gtk.LinkButton`; se usa ese |
| A-asistente | Numerales pequeños | Numerales `large` bold | Firma del lanzador del pipeline |
| A-status-falla | Icono con ondas | Igual: las ondas solo en alertas | Firma |

## Inventario de componentes y estados

### Icono de bandeja
- Estados: los 10 titulares de la dirección de arte, cada uno con su glifo y color.
- Tooltip: el titular y la hora de la última sincronización ("Up to date · synced 2 minutes ago").
- Clic izquierdo: abre o enfoca la ventana. Clic derecho: menú.
- Sin bandeja disponible (ni XApp ni AppIndicator): cerrar la ventana cierra la app, y la
  sincronización sigue igual porque vive en systemd.

### Menú de la bandeja
- Línea de estado (inactiva), "Open loudsync", "Open folder", "Sync now", "Pause syncing ▸"
  (1 hour / 8 hours / Until I resume) o "Resume syncing", "Review conflicts (N)…" solo si
  N > 0, y "Quit (syncing keeps running)".
- "Sync now" se deshabilita mientras hay una corrida en curso.

### Página Status
| Estado | Icono | Frase | Línea secundaria | Extra |
|---|---|---|---|---|
| setup | engranaje, syncing | "Let's set up loudsync" | "Nothing has been synced yet." | Botón "Set up…" en lugar de la fila de botones |
| broken | error + ondas | "loudsync can't start" | mensaje del motor | Info bar con el texto del motor y "Open settings" / "Open log" |
| decision | error + ondas | "Sync is stopped: it needs your decision" | la razón del motor | Info bar con "Review the plan…" |
| failing | error + ondas | "Sync is failing" | "N attempts in a row · last good sync …" | Info bar con la causa si el motor la conoce, si no "Open log" |
| syncing | flechas, syncing | "Syncing…" | "Last synced …" | Spinner en la barra de título |
| paused | pausa, paused | "Paused until 15:40" / "Paused" | "Resumes by itself at that time." / "…at your next login at the latest." | "Resume" reemplaza a "Pause" |
| retrying | advertencia, warning | "The last attempt failed" | "Retrying every minute. You'll be alerted after N in a row." | — |
| conflicts | advertencia + ondas, warning | "N files need a decision" | "Last synced …" | Botón "Review conflicts" |
| off | pausa, paused | "Automatic sync is off" | "Nothing syncs until you turn it on." | Botón "Turn on" |
| ok | check, ok | "Up to date" | "Last synced …" | — |

La ficha (carpeta, remoto, subidas instantáneas, revisión del remoto, repos excluidos) se
muestra en todos los estados menos setup. "Instant uploads: Off" lleva una línea de ayuda
si el watcher no corre ("Install inotify-tools to upload within seconds").

### Página Conflicts
- Vacío: "Nothing to decide." + "When a file changes on both sides, both versions are kept and listed here."
- Con conflictos: fila por archivo con nombre, carpeta, las dos versiones (origen · fecha ·
  tamaño) y los botones "Open both", "Keep current", "Keep other copy".
- Nota de carrera cuando las fechas están a menos de `CONFLICT_RACE_SECONDS`.
- Ocupado: los botones de la fila se deshabilitan mientras se mueve el archivo.
- Error: si el archivo ya no existe, la fila lo dice ("Already settled elsewhere") y se
  refresca la lista. Si la papelera no está disponible, no se borra nada: se avisa.

### Página Activity
- Lista de las últimas corridas y eventos, del más nuevo al más viejo, con un punto de color
  por tipo (done = ok, failed/error/attention = error, conflict/postponed = warning).
- Vacío: "No runs recorded yet."
- Botón "Open full log".

### Página Settings
- Secciones "What to sync", "Behaviour", "Startup" y "Advanced" (desplegable) según la
  maqueta A-settings.
- Estados de "Apply": deshabilitado sin cambios, habilitado con cambios, y con los errores
  de validación inline bajo la fila correspondiente.
- Cambiar la carpeta o el remoto abre una confirmación: se pausa, se corre una vista previa
  (dry run) con el conteo de archivos a copiar, luego la primera sincronización, y se reanuda.

### Página Filters
- Editor de texto monoespaciado de `filters-base.txt` con "Save" y "Revert", y una nota:
  "Saving reconciles the sync on the next run. Nothing is deleted."
- Lista de solo lectura de los repos git excluidos.

### Asistente de primera configuración
Pasos: 1 Folder, 2 Cloud account, 3 What stays out, 4 First sync.
- "Next" se deshabilita hasta que el paso es válido.
- Conectar una cuenta muestra el progreso de rclone ("Waiting for you to sign in in your
  browser…") con "Technical details" desplegable, y un error franco si falla.
- El paso 4 corre la vista previa, muestra el conteo y pide confirmación antes de la
  primera sincronización real.

## Ajustes al construir (27-09-2026)

Revisados con `gui/tools/snapshot.py`, que renderiza cada página en cada estado:

- En "needs a decision" no se ofrece "Sync now": una corrida normal se volvería a detener.
- En pausa o apagado, el botón principal es "Resume" / "Turn on"; "Sync now" deja de ser
  el sugerido, para que haya una sola acción principal.
- La falla por archivos ajenos se dice en lenguaje llano; el código 403 del proveedor
  queda en "Technical details".
- Íconos de bandeja: los estados tranquilos son simbólicos (los colorea el panel), las
  alertas van en color con ondas. Colores de bandeja validados a 3:1 contra panel claro
  y oscuro (`design-tokens.json`).
- El glifo de advertencia de cada conflicto es el del ícono propio: el carácter ⚠ de la
  fuente ignoraba el color.

Aprobado por operador: sí — 27-09-2026 ("está bueno, procedo", tras revisar las maquetas de la ronda 1)
