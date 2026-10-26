# tv
# Qué ver Chile

Guía inicial de noticias de televisión chilena, farándula, realities y entretención.

## Archivos

- `index.html`: interfaz de la guía.
- `manifest.json`: configuración de instalación.
- `icon.svg`: icono.
- `sw.js`: caché básica para uso sin conexión.
- `data/tv-data.json`: datos que consume la página.
- `scripts/update_data.py`: recopilación de noticias.
- `.github/workflows/update-data.yml`: actualización automática.

## Publicar con GitHub Pages

1. Sube todos los archivos manteniendo exactamente las carpetas indicadas.
2. Abre Settings > Pages.
3. En Build and deployment, elige Deploy from a branch.
4. Selecciona la rama `main` y la carpeta `/ (root)`.
5. Guarda y espera a que GitHub publique la página.

## Activar la actualización

1. Abre la pestaña Actions.
2. Habilita los workflows si GitHub te lo solicita.
3. Ejecuta manualmente `Actualizar datos de TV` con Run workflow.
4. Comprueba que termine correctamente y que se actualice `data/tv-data.json`.

El workflow también intenta ejecutarse cada 30 minutos. GitHub puede retrasar las ejecuciones programadas.

## Limitaciones de esta versión

- Recopila resultados de Google News RSS; no es una API de programación televisiva.
- No confirma horarios, invitados ni temas solo por aparecer en una noticia.
- Una fuente oficial se etiqueta como probable, no como confirmación automática.
- Si una consulta falla, el detalle queda registrado en `errors`.
- Para mostrar una parrilla fiable se deben integrar y comprobar fuentes específicas de cada canal.

## Instalar en iPhone

Cuando la web esté publicada, ábrela en Safari, toca Compartir y selecciona Añadir a pantalla de inicio.
