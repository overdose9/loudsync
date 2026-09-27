# Dirección de arte — interfaz de loudsync

Documento rector del diseño de la interfaz gráfica. `design.md` (insumo de Stitch),
`design-tokens.json` y `design-notes.md` se derivan de este archivo. Ante cualquier
discrepancia manda este documento, y se corrigen los derivados.

**Ruta de generación: A (Stitch), solo como maqueta.** loudsync no tiene un sistema de
diseño aprobado, así que corresponde explorar direcciones. Las pantallas de Stitch fijan
la distribución, la jerarquía y el tono. La implementación es GTK3 nativo y hereda
superficies, tipografía y radios del tema del usuario. Lo que Stitch proponga en colores
de fondo o fuentes no se traslada (decidido por el operador el 27-09-2026).

## Concepto rector

**Respalda y sincroniza tus archivos con la certeza de un vigía que grita cuando algo
falla.** (Formulado por el operador, 27-09-2026.)

La certeza es lo que se diseña. La interfaz solo afirma lo que puede probar: "Up to date"
sale de una corrida real que terminó bien, con su hora, nunca de suponer que todo anda.
Cuando todo funciona no pide atención. Cuando algo falla, no hay forma de no verlo, y dice
qué hacer.

Tres palabras gobiernan cada decisión:

1. **Certera.** Cada afirmación tiene respaldo: una hora, una corrida, un archivo. Si no
   se sabe algo, se dice que no se sabe ("never synced", "no data yet") en vez de mostrar
   un estado optimista por defecto.
2. **Serena.** En el estado normal no hay números, gráficos ni badges. Una frase y una
   hora. La calma es la señal de que se puede confiar en ella.
3. **Franca y accionable.** Cada problema dice lo que pasa y lo que cuesta, sin
   eufemismos ("Sync is failing", no "Having trouble connecting"), y trae su botón. Si no
   hay nada que hacer, no se muestra como problema.

## Paleta

Las superficies, el texto y los acentos vienen del tema del usuario (Orchis-Dark en la
máquina del autor, Mint-Y por defecto en Mint). Pisar el tema rompe el modo oscuro y las
preferencias de accesibilidad, y hace que la app se vea ajena al escritorio.

loudsync pone color **solo al estado**, en el ícono grande de la página de estado, en el
ícono de la bandeja y en el punto junto a cada entrada de la actividad. Cada rol tiene una
variante para tema claro y otra para oscuro, elegida en tiempo de ejecución según la
luminancia del fondo del tema.

| Rol | Claro | Oscuro | Cuándo | Contraste mínimo verificado |
|---|---|---|---|---|
| `ok` | `#1b6e45` | `#5fcf8f` | Al día | 5,8:1 claro / 6,8:1 oscuro |
| `syncing` | `#1a5bb0` | `#74aeff` | Sincronizando, configurar | 5,9:1 / 6,0:1 |
| `paused` | `#565d6b` | `#b3bac7` | Pausado, automatización apagada | 6,2:1 / 6,6:1 |
| `warning` | `#9a4300` | `#ffa566` | Conflictos, reintentando | 6,1:1 / 6,3:1 |
| `error` | `#b0241b` | `#ff8f85` | Falla, bloqueado, requiere decisión | 6,2:1 / 5,6:1 |

Todas las combinaciones se validaron con `check-contrast.py` del pipeline contra los
fondos de Mint-Y, Adwaita, Orchis-Dark y Mint-Y-Dark, a 4,5:1 (texto normal, aunque en la
mayoría de los usos son íconos, que exigen solo 3:1). El estado nunca depende solo del
color: cada uno tiene su glifo y su frase.

## Tipografía

La fuente de interfaz del sistema, sin excepción. La jerarquía sale de tamaño y peso, con
una escala de razón 1,2 expresada en tamaños Pango:

| Nivel | Pango | Uso |
|---|---|---|
| display | `xx-large` bold | La frase de estado ("Up to date") |
| headline | `x-large` bold | Título de cada página |
| title | `large` bold | Encabezados de sección, numerales del asistente |
| body | normal | Texto |
| caption | `small` + `dim-label` | Ayudas bajo cada opción, horas |

Monoespaciada del sistema solo para rutas, nombres de remoto y el desplegable "Technical
details".

## Gesto de layout

**La respuesta primero, el detalle debajo.** Cada página abre con una frase que responde
la pregunta que te trajo ahí ("¿está funcionando?", "¿qué tengo que decidir?"), y la
información de respaldo queda más abajo o dentro de un desplegable. Es el patrón del
lanzador del pipeline: opción clara, una línea de ayuda y lo técnico escondido.

- **Bandeja**: el ícono es la interfaz principal, como en Drive o OneDrive. El clic
  izquierdo abre la ventana y el derecho abre el menú.
- **Ventana**: barra lateral con cinco páginas y contenido a la derecha, de ancho
  máximo contenido (no se estira a 1920 px).
- **Asistente de primera configuración**: pasos numerados con numerales grandes
  (1, 2, 3…), como las opciones del lanzador. Una decisión por paso.

```
Bandeja (clic derecho)            Ventana — página Status
┌──────────────────────────┐      ┌─────────────┬──────────────────────────────────────┐
│ ● Up to date · 2 min ago │      │ ● Status    │  [ícono de estado 64px]              │
│──────────────────────────│      │   Conflicts │  Up to date                          │
│ Open loudsync            │      │   Activity  │  Last synced 2 minutes ago           │
│ Open folder              │      │   Settings  │                                      │
│ Sync now                 │      │   Filters   │  [Sync now] [Pause ▾] [Open folder]  │
│ Pause syncing          ▸ │      │             │                                      │
│──────────────────────────│      │             │  ~/Documentos  ⇄  gdrive_personal:…  │
│ Quit (sync keeps running)│      │             │  Instant uploads      on             │
└──────────────────────────┘      │             │  Checks remote        every minute   │
                                  │             │  Git repos excluded   22  ▸          │
                                  └─────────────┴──────────────────────────────────────┘

Status con falla: la frase cambia y aparece la causa con su acción.
┌───────────────────────────────────────────────┐
│ [ícono error]  Sync is failing                │
│ 4 attempts in a row since 14:02               │
│ ┌───────────────────────────────────────────┐ │
│ │ 3 files on the remote belong to another   │ │
│ │ account, so this one can't delete them.   │ │
│ │ [Show the files]  [Open log]              │ │
│ └───────────────────────────────────────────┘ │
└───────────────────────────────────────────────┘
```

## Lenguaje de movimiento

Casi ninguno, y a propósito: una herramienta que "está tranquila" no se mueve. El único
movimiento continuo es el spinner mientras corre una sincronización. Las transiciones
entre páginas y los desplegables usan 200 ms ease-out de GTK, y desaparecen si el
usuario desactivó las animaciones (`gtk-enable-animations`).

## Iconografía (en lugar de fotografía)

**El detalle con firma es el ícono.** Una nube con tres ondas de sonido saliendo del
costado: el "loud" de loudsync. En la bandeja es un ícono simbólico (recoloreable por el
tema), con el glifo del estado dentro de la nube:

| Estado | Glifo |
|---|---|
| Al día | check |
| Sincronizando | dos flechas en círculo |
| Pausado | dos barras |
| Conflictos, reintentando | signo de exclamación en triángulo |
| Falla, bloqueado, decisión | signo de exclamación en círculo |
| Configurar | engranaje |

Las ondas de sonido aparecen solo en los estados de alerta: la nube "grita" cuando hay
algo que atender y está callada cuando no. Así el concepto queda dentro del ícono.

**Ícono de la aplicación: "Noche"** (elegido por el operador el 27-09-2026 entre
"Noche", "Aurora" y "Alerta"; comparación en `icono-app-variantes.png`). Es el único lugar
donde se muestra la marca y no un estado, por eso va a todo color y con profundidad:
azulejo de cielo nocturno con estrellas tenues, la nube blanca con el check de una
sincronización terminada (la certeza), y el grito saliendo de ella en ámbar a rojo con
brillo (el vigía). Usa la misma nube y las mismas ondas que los íconos de bandeja, así que
ambos se leen como una familia. Lo genera `icons.app_icon()`.

## Tono de voz

- **Idioma de la interfaz: inglés**, igual que el motor, sus notificaciones y el README.
  Mezclar idiomas entre la ventana y las notificaciones sería la verdadera inconsistencia.
  Todo el texto pasa por gettext, así que una traducción al español es agregar un
  archivo, no reescribir.
- Segunda persona, frases cortas, verbos concretos. Qué pasó, qué significa y qué hacer.
- Nunca minimizar: "Sync is failing", no "Something went wrong".
- Nunca alarmar sin motivo: una carrera consigo mismo es "Conflict resolved: nothing was
  lost", no una alerta crítica (la misma calibración que ya tiene el motor).
- Frases de marca candidatas (derivadas del concepto):
  1. "Backs up and syncs your files. Shouts when something breaks."
  2. "Quiet when it works. Loud when it doesn't."
  3. "Certainty, not confidence you haven't earned." (eco del README)

## Estados que la interfaz tiene que resolver

La lista completa con sus componentes va en `design-notes.md`. Los titulares, en orden
de prioridad (se muestra el primero que aplique):

1. **Setup**: nunca se ha sincronizado. Lleva al asistente.
2. **Broken**: el motor no puede ni arrancar (remoto borrado, carpeta inexistente). Muestra
   el mensaje del motor.
3. **Needs a decision**: un plan de renombres demasiado grande. Muestra el plan y un botón
   para aplicarlo.
4. **Failing**: fallas que ya superaron el umbral de alerta. Muestra la causa si el motor
   la conoce.
5. **Syncing**.
6. **Paused**: hasta cuándo, y un botón para reanudar.
7. **Retrying**: falló una o dos veces, todavía bajo el umbral.
8. **Conflicts**: N archivos esperan una decisión.
9. **Off**: la sincronización automática está apagada.
10. **Up to date**.

Aprobado por operador: sí — 27-09-2026 ("está bueno, procedo", tras revisar las maquetas de la ronda 1)
