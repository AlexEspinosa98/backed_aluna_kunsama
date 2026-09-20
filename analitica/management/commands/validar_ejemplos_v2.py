"""`python manage.py validar_ejemplos_v2` — corre la validación v2 (analitica/v2/validacion.py)
sobre los ejemplos congelados de la entrega y sobre un puñado de mutaciones que DEBEN rechazarse.
Es la verificación de la fase 1 del plan (docs/mejora_promps/plan_implementacion/) y una forma de
comprobar cambios en validacion.py sin correr la suite completa.

Con `--analisis <id>` valida en su lugar el `resultado` de un AnalisisV2 guardado contra su propia
`entrada` inmutable (útil para QA de una respuesta real del modelo)."""
import copy
import json

from django.core.management.base import BaseCommand, CommandError

from analitica.v2.contrato import RECURSOS
from analitica.v2.validacion import validar_esquema, validar_negocio, validar_salida


class Command(BaseCommand):
    help = 'Valida los ejemplos congelados del contrato v2 (o un AnalisisV2 guardado con --analisis).'

    def add_arguments(self, parser):
        parser.add_argument('--analisis', type=int, default=None, help='id de un AnalisisV2 guardado')

    def handle(self, *args, **options):
        if options['analisis'] is not None:
            return self._validar_analisis_guardado(options['analisis'])
        self._validar_ejemplos()

    def _validar_analisis_guardado(self, analisis_id):
        from analitica.models import AnalisisV2

        try:
            analisis = AnalisisV2.objects.get(pk=analisis_id)
        except AnalisisV2.DoesNotExist as exc:
            raise CommandError(f'No existe AnalisisV2 {analisis_id}') from exc
        if not analisis.resultado:
            raise CommandError(f'AnalisisV2 {analisis_id} no tiene resultado (estado={analisis.estado})')
        errores = validar_salida(analisis.resultado, analisis.entrada, pipeline_esperado=analisis.pipeline)
        if errores:
            for error in errores:
                self.stdout.write(self.style.ERROR(f'  - {error}'))
            raise CommandError(f'{len(errores)} error(es) en AnalisisV2 {analisis_id}')
        self.stdout.write(self.style.SUCCESS(f'OK AnalisisV2 {analisis_id}: esquema y reglas de negocio'))

    def _validar_ejemplos(self):
        carpeta = RECURSOS / 'ejemplos'
        salidas = sorted(carpeta.glob('*.salida.json'))
        if not salidas:
            raise CommandError(f'No hay ejemplos en {carpeta}')
        pares = 0
        for ruta in salidas:
            salida = json.loads(ruta.read_text(encoding='utf-8'))
            errores = validar_esquema(salida)
            ruta_entrada = ruta.with_name(ruta.name.replace('.salida.', '.entrada.'))
            if not errores and ruta_entrada.exists():
                entrada = json.loads(ruta_entrada.read_text(encoding='utf-8'))
                errores = validar_negocio(salida, entrada, pipeline_esperado=salida['pipeline'])
                pares += 1
            if errores:
                for error in errores:
                    self.stdout.write(self.style.ERROR(f'  - {error}'))
                raise CommandError(f'{ruta.name}: {len(errores)} error(es)')
            self.stdout.write(f'OK {ruta.name}')

        # Mutaciones que DEBEN rechazarse (mismas cuatro de verificar_entrega.py + dos propias).
        original = json.loads((carpeta / 'llm_integral.salida.json').read_text(encoding='utf-8'))
        entrada = json.loads((carpeta / 'llm_integral.entrada.json').read_text(encoding='utf-8'))
        mutantes = []
        m = copy.deepcopy(original); m['html'] = '<p>No permitido</p>'; mutantes.append(('clave extra', m))
        m = copy.deepcopy(original); m['informes'][0]['hallazgos'][0]['metricas'][0]['valor'] = 90; mutantes.append(('porcentaje falso', m))
        m = copy.deepcopy(original); m['informes'][0]['hallazgos'][0]['citas'][0]['texto'] = 'Cita inventada'; mutantes.append(('cita no literal', m))
        m = copy.deepcopy(original); m['informes'][0]['hallazgos'][0]['visualizacion_ids'] = ['no-existe']; mutantes.append(('visualización inexistente', m))
        m = copy.deepcopy(original); m['cobertura'] = m['cobertura'][:-1]; mutantes.append(('cobertura incompleta', m))
        m = copy.deepcopy(original); m['fuentes'][0]['cobertura'] = 'parcial'; mutantes.append(('fuente alterada', m))
        for nombre, mutante in mutantes:
            errores = validar_salida(mutante, entrada, pipeline_esperado='llm')
            if not errores:
                raise CommandError(f'La mutación "{nombre}" fue aceptada y debía rechazarse')
            self.stdout.write(f'OK rechazada: {nombre} ({errores[0][:90]}…)')
        self.stdout.write(self.style.SUCCESS(
            f'Esquema y reglas OK: {len(salidas)} salidas, {pares} pares con entrada, {len(mutantes)} mutaciones rechazadas.'
        ))
