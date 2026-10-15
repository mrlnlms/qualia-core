"""Política geral de decodificação contínua, sem pós-processamento textual.

Importar este módulo não carrega modelos. A política sem histórico textual foi
ensaiada com large-v3/pt; não implica validação de outros modelos ou idiomas.
"""

DEFAULT_DECODER_PARAMS = {'no_context': True, 'n_max_text_ctx': 0}


def decoder_params(overrides=None):
    """Valida as duas opções de histórico e devolve configuração independente."""
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError('decoder_params deve ser um objeto')
    overrides = {} if overrides is None else overrides
    if set(overrides) - set(DEFAULT_DECODER_PARAMS):
        raise ValueError('Parâmetro de decoder desconhecido')
    result = {**DEFAULT_DECODER_PARAMS, **overrides}
    if type(result['no_context']) is not bool:
        raise ValueError('no_context deve ser booleano')
    if type(result['n_max_text_ctx']) is not int or result['n_max_text_ctx'] < 0:
        raise ValueError('n_max_text_ctx deve ser inteiro não negativo')
    return result


def transcription_policy(data):
    """Lê opções explícitas ou efetivas; ausência de evidência não é default novo."""
    value = data.get('decoder_params', data.get('effective_decoder_params', {}))
    if not isinstance(value, dict) or any(k not in value for k in DEFAULT_DECODER_PARAMS):
        return None
    try:
        return decoder_params({k: value[k] for k in DEFAULT_DECODER_PARAMS})
    except ValueError:
        return None


def decode_segments(waveform, model_name, language, params=None, model_factory=None):
    """Modelo novo por áudio; preserva integralmente texto, ordem e tempos nativos.

    model_factory permite testar o contrato sem carregar pesos. Modelos, callbacks
    e estado de amostragem não são compartilhados entre gravações.
    """
    options = decoder_params(params)
    if model_factory is None:
        from pywhispercpp.model import Model
        model_factory = Model
    model = model_factory(model_name, params_sampling_strategy=0, n_threads=4,
                          print_progress=False, print_realtime=False,
                          redirect_whispercpp_logs_to=None, **options)
    try:
        result = model.transcribe(waveform, language=language)
        return [{'start': s.t0 / 100, 'end': s.t1 / 100, 'text': s.text} for s in result]
    finally:
        del model
