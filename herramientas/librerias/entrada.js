// Librerías de interfaz del tablero (index.html), empaquetadas en assets/vendor/.
// Se reconstruyen con:  cd herramientas/librerias && npm ci && npm run construir
import { animate } from "motion/mini";       // motiondivision/motion (MIT): animaciones (versión liviana)
import TomSelect from "tom-select";                    // orchidjs/tom-select (Apache-2.0): selector con búsqueda
import tippy from "tippy.js";                          // atomiks/tippyjs (MIT): ayudas y menús desplegables
import NumberFlow, { define } from "number-flow";      // barvian/number-flow (MIT): cifras que ruedan

define("number-flow", NumberFlow);
window.Motion = { animate };
window.TomSelect = TomSelect;
window.tippy = tippy;
