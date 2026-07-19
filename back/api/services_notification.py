"""Synchronous notification domain service, ready for a future worker adapter."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import EventoNotificacao, Notificacao, PreferenciaComunicacao


def _registrar_evento(notificacao, acao, usuario=None, detalhes=''):
    return EventoNotificacao.objects.create(notificacao=notificacao, usuario=usuario, acao=acao, detalhes=detalhes)


def criar_notificacao(
    *,
    paciente,
    canal,
    mensagem,
    agendada_para,
    criada_por=None,
    assunto='',
    agendamento=None,
    orcamento=None,
    template=None,
):
    if not mensagem or not mensagem.strip():
        raise ValidationError({'mensagem': 'Mensagem nao pode ser vazia.'})
    if template and not template.ativo:
        raise ValidationError({'template': 'Template inativo nao pode ser usado.'})
    if agendamento and (agendamento.paciente_id != paciente.id or agendamento.clinica_id != paciente.clinica_id):
        raise ValidationError({'agendamento': 'Agendamento incompativel com o paciente.'})
    if orcamento and (orcamento.paciente_id != paciente.id or orcamento.clinica_id != paciente.clinica_id):
        raise ValidationError({'orcamento': 'Orcamento incompativel com o paciente.'})
    notificacao = Notificacao.objects.create(
        clinica=paciente.clinica,
        paciente=paciente,
        agendamento=agendamento,
        orcamento=orcamento,
        template=template,
        canal=canal,
        assunto=assunto,
        mensagem=mensagem.strip(),
        agendada_para=agendada_para,
        criada_por=criada_por,
    )
    _registrar_evento(notificacao, 'CRIACAO', criada_por)
    return notificacao


def criar_lembrete_consulta(agendamento, usuario=None):
    """Creates internal 24h/2h records; dispatching stays deliberately out of scope."""
    preferencias, _ = PreferenciaComunicacao.objects.get_or_create(paciente=agendamento.paciente)
    if not preferencias.aceita_whatsapp:
        return []
    texto = f'Lembrete de consulta em {agendamento.data_horario.isoformat()}.'
    return [
        criar_notificacao(
            paciente=agendamento.paciente,
            agendamento=agendamento,
            canal='WHATSAPP',
            mensagem=texto,
            agendada_para=agendamento.data_horario - timedelta(hours=horas),
            criada_por=usuario,
        )
        for horas in (24, 2)
    ]


def cancelar_notificacoes(agendamento, usuario=None):
    with transaction.atomic():
        notificacoes = Notificacao.objects.select_for_update().filter(
            agendamento=agendamento, status__in=['PENDENTE', 'PROCESSANDO']
        )
        for notificacao in notificacoes:
            notificacao.status = 'CANCELADA'
            notificacao.save(update_fields=['status', 'atualizado_em'])
            _registrar_evento(notificacao, 'CANCELAMENTO', usuario)
    return notificacoes.count()


def registrar_envio(notificacao, usuario=None):
    if notificacao.status == 'CANCELADA':
        raise ValidationError({'status': 'Notificacao cancelada nao pode ser enviada.'})
    notificacao.status, notificacao.enviada_em, notificacao.erro = 'ENVIADA', timezone.now(), ''
    notificacao.save(update_fields=['status', 'enviada_em', 'erro', 'atualizado_em'])
    _registrar_evento(notificacao, 'TENTATIVA_ENVIO', usuario)
    return notificacao


def registrar_erro(notificacao, erro, usuario=None):
    notificacao.status, notificacao.erro = 'ERRO', (erro or 'Falha de envio.')[:2000]
    notificacao.save(update_fields=['status', 'erro', 'atualizado_em'])
    _registrar_evento(notificacao, 'ERRO_ENVIO', usuario, notificacao.erro)
    return notificacao


def confirmar_presenca(agendamento, usuario=None):
    """Internal audit state for a future signed link/adapter flow."""
    from .services import confirmar_agendamento

    agendamento = confirmar_agendamento(agendamento)
    notificacao = Notificacao.objects.filter(agendamento=agendamento).order_by('-id').first()
    if notificacao:
        _registrar_evento(notificacao, 'CONFIRMACAO', usuario)
    return agendamento
