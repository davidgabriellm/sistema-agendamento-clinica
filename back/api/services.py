from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from .models import (
    Agendamento,
    BloqueioAgendaClinica,
    HorarioFuncionamentoClinica,
    IndisponibilidadeDentista,
    Orcamento,
    Pagamento,
    Parcela,
)


class ConflitoAgenda(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Horario indisponivel para este dentista.'
    default_code = 'conflito_agenda'


STATUS_BLOQUEIAM_HORARIO = {
    Agendamento.STATUS_AGENDADA,
    Agendamento.STATUS_CONFIRMADA,
    Agendamento.STATUS_EM_ATENDIMENTO,
    Agendamento.STATUS_CONCLUIDA,
}

STATUS_FINAIS = {
    Agendamento.STATUS_CANCELADA,
    Agendamento.STATUS_CONCLUIDA,
    Agendamento.STATUS_NAO_COMPARECEU,
}


def calcular_duracao_minutos(clinica=None, procedimento_ref=None, duracao_minutos=None):
    if procedimento_ref and procedimento_ref.duracao_minutos:
        return procedimento_ref.duracao_minutos
    if duracao_minutos:
        return duracao_minutos
    if clinica and clinica.duracao_padrao_consulta_minutos:
        return clinica.duracao_padrao_consulta_minutos
    return 30


def calcular_data_hora_fim(data_horario, duracao_minutos):
    return data_horario + timedelta(minutes=duracao_minutos)


def validar_data_futura(data_horario):
    if not data_horario:
        raise ValidationError({'data_horario': 'Informe a data e hora do agendamento.'})
    if data_horario <= timezone.now():
        raise ValidationError({'data_horario': 'Agendamento nao pode ser criado ou reagendado no passado.'})


def validar_recursos_ativos(dentista, procedimento_ref=None):
    if dentista and not dentista.ativo:
        raise ValidationError({'dentista': 'Dentista inativo nao pode receber agendamentos.'})
    if procedimento_ref and not procedimento_ref.ativo:
        raise ValidationError({'procedimento_ref': 'Procedimento inativo nao pode ser usado em agendamentos.'})


def validar_sobreposicao(dentista, inicio, fim, agendamento_atual=None):
    conflitos = (
        Agendamento.objects.select_for_update()
        .filter(dentista=dentista, status__in=STATUS_BLOQUEIAM_HORARIO)
        .order_by('data_horario')
    )
    if agendamento_atual:
        conflitos = conflitos.exclude(pk=agendamento_atual.pk)

    for agendamento in conflitos:
        fim_existente = agendamento.data_hora_fim or calcular_data_hora_fim(
            agendamento.data_horario,
            agendamento.duracao_minutos,
        )
        if agendamento.data_horario < fim and fim_existente > inicio:
            raise ConflitoAgenda('Horario se sobrepoe a outro agendamento deste dentista.')


def preparar_janela_agendamento(data_horario, clinica=None, procedimento_ref=None, duracao_minutos=None):
    duracao = calcular_duracao_minutos(clinica, procedimento_ref, duracao_minutos)
    return duracao, calcular_data_hora_fim(data_horario, duracao)


def validar_horario_funcionamento(clinica, inicio, fim):
    if not clinica:
        raise ValidationError({'clinica': 'A clinica e obrigatoria para validar o horario de funcionamento.'})

    timezone_clinica = ZoneInfo(clinica.timezone)
    inicio_local = timezone.localtime(inicio, timezone_clinica)
    fim_local = timezone.localtime(fim, timezone_clinica)

    if inicio_local.date() != fim_local.date():
        raise ValidationError({'data_horario': 'Agendamento deve iniciar e terminar no mesmo dia local da clinica.'})

    horarios = HorarioFuncionamentoClinica.objects.filter(
        clinica=clinica,
        dia_semana=inicio_local.weekday(),
        ativo=True,
    )

    if not horarios.exists():
        raise ValidationError({'data_horario': 'Clinica nao possui expediente ativo neste dia.'})

    inicio_hora = inicio_local.time()
    fim_hora = fim_local.time()
    for horario in horarios:
        if horario.horario_inicio <= inicio_hora and fim_hora <= horario.horario_fim:
            return

    raise ValidationError({'data_horario': 'Agendamento fora do horario de funcionamento da clinica.'})


def validar_bloqueios_e_indisponibilidades(clinica, dentista, inicio, fim):
    bloqueio = BloqueioAgendaClinica.objects.filter(
        clinica=clinica,
        ativo=True,
        inicio__lt=fim,
        fim__gt=inicio,
    ).exists()
    if bloqueio:
        raise ConflitoAgenda('Horario bloqueado para esta clinica.')

    indisponibilidade = IndisponibilidadeDentista.objects.filter(
        clinica=clinica,
        dentista=dentista,
        ativo=True,
        inicio__lt=fim,
        fim__gt=inicio,
    ).exists()
    if indisponibilidade:
        raise ConflitoAgenda('Dentista indisponivel neste horario.')


def validar_agendamento_criacao_ou_reagendamento(
    *,
    clinica,
    dentista,
    data_horario,
    procedimento_ref=None,
    duracao_minutos=None,
    agendamento_atual=None,
):
    validar_data_futura(data_horario)
    validar_recursos_ativos(dentista, procedimento_ref)
    duracao, fim = preparar_janela_agendamento(data_horario, clinica, procedimento_ref, duracao_minutos)
    validar_horario_funcionamento(clinica, data_horario, fim)
    validar_bloqueios_e_indisponibilidades(clinica, dentista, data_horario, fim)
    validar_sobreposicao(dentista, data_horario, fim, agendamento_atual)
    return duracao, fim


def cancelar_agendamento(agendamento, usuario=None):
    if agendamento.status in {Agendamento.STATUS_CANCELADA, Agendamento.STATUS_CONCLUIDA}:
        raise ValidationError({'status': 'Agendamento concluido ou cancelado nao pode ser cancelado.'})
    if usuario and not usuario.is_staff and usuario.tipo == 'PACIENTE':
        antecedencia = agendamento.clinica.antecedencia_minima_cancelamento_horas
        limite_cancelamento = timezone.now() + timedelta(hours=antecedencia)
        if agendamento.data_horario < limite_cancelamento:
            raise ValidationError({'data_horario': 'Cancelamento fora da antecedencia minima da clinica.'})
    agendamento.status = Agendamento.STATUS_CANCELADA
    agendamento.save(update_fields=['status'])
    return agendamento


def confirmar_agendamento(agendamento):
    if agendamento.status in STATUS_FINAIS:
        raise ValidationError({'status': 'Agendamento finalizado nao pode ser confirmado.'})
    agendamento.status = Agendamento.STATUS_CONFIRMADA
    agendamento.save(update_fields=['status'])
    return agendamento


def concluir_agendamento(agendamento):
    if agendamento.status == Agendamento.STATUS_CANCELADA:
        raise ValidationError({'status': 'Agendamento cancelado nao pode ser concluido.'})
    if agendamento.status == Agendamento.STATUS_CONCLUIDA:
        raise ValidationError({'status': 'Agendamento ja esta concluido.'})
    agendamento.status = Agendamento.STATUS_CONCLUIDA
    agendamento.save(update_fields=['status'])
    return agendamento


def marcar_falta_agendamento(agendamento):
    if agendamento.status in {Agendamento.STATUS_CANCELADA, Agendamento.STATUS_CONCLUIDA}:
        raise ValidationError({'status': 'Agendamento cancelado ou concluido nao pode ser marcado como falta.'})
    agendamento.status = Agendamento.STATUS_NAO_COMPARECEU
    agendamento.save(update_fields=['status'])
    return agendamento


def reagendar_agendamento(agendamento, nova_data_horario):
    if agendamento.status in {Agendamento.STATUS_CANCELADA, Agendamento.STATUS_CONCLUIDA}:
        raise ValidationError({'status': 'Agendamento cancelado ou concluido nao pode ser reagendado.'})
    with transaction.atomic():
        duracao, fim = validar_agendamento_criacao_ou_reagendamento(
            clinica=agendamento.clinica,
            dentista=agendamento.dentista,
            data_horario=nova_data_horario,
            procedimento_ref=agendamento.procedimento_ref,
            duracao_minutos=agendamento.duracao_minutos,
            agendamento_atual=agendamento,
        )
        agendamento.data_horario = nova_data_horario
        agendamento.duracao_minutos = duracao
        agendamento.data_hora_fim = fim
        agendamento.save(update_fields=['data_horario', 'duracao_minutos', 'data_hora_fim'])
    return agendamento


def validar_criacao_evolucao(*, prontuario, agendamento, dentista):
    """Protege os vinculos que formam o registro clinico historico."""
    if prontuario.clinica_id != agendamento.clinica_id:
        raise ValidationError({'agendamento': 'Agendamento pertence a outra clinica.'})
    if dentista.clinica_id != prontuario.clinica_id:
        raise ValidationError({'dentista': 'Dentista pertence a outra clinica.'})
    if agendamento.dentista_id != dentista.id:
        raise ValidationError({'dentista': 'Dentista deve ser o vinculado ao atendimento.'})
    if agendamento.paciente_id != prontuario.paciente_id:
        raise ValidationError({'agendamento': 'Agendamento pertence a outro paciente.'})
    if agendamento.status not in {Agendamento.STATUS_EM_ATENDIMENTO, Agendamento.STATUS_CONCLUIDA}:
        raise ValidationError(
            {'agendamento': 'Evolucao clinica so pode ser registrada em atendimento ou consulta concluida.'}
        )


NUMEROS_DENTES_FDI = set(range(11, 19)) | set(range(21, 29)) | set(range(31, 39)) | set(range(41, 49))
TRANSICOES_PLANO = {
    'RASCUNHO': {'PROPOSTO'},
    'PROPOSTO': {'APROVADO', 'CANCELADO'},
    'APROVADO': {'EM_ANDAMENTO', 'CANCELADO'},
    'EM_ANDAMENTO': {'CONCLUIDO', 'CANCELADO'},
}


def validar_dente(numero_dente):
    if numero_dente not in NUMEROS_DENTES_FDI:
        raise ValidationError({'numero_dente': 'Numero de dente deve usar a numeracao FDI permanente valida.'})


def validar_contexto_odontologico(*, prontuario, clinica, dentista=None):
    if prontuario.clinica_id != clinica.id:
        raise ValidationError({'prontuario': 'Prontuario pertence a outra clinica.'})
    if dentista and dentista.clinica_id != clinica.id:
        raise ValidationError({'dentista': 'Dentista pertence a outra clinica.'})


def transicionar_plano(plano, novo_status):
    if novo_status not in TRANSICOES_PLANO.get(plano.status, set()):
        raise ValidationError({'status': f'Transicao de {plano.status} para {novo_status} nao permitida.'})
    plano.status = novo_status
    agora = timezone.now()
    if novo_status == 'APROVADO':
        plano.aprovado_em = agora
    if novo_status == 'CONCLUIDO':
        plano.concluido_em = agora
    plano.save()
    return plano


CENTAVO = Decimal('0.01')
TRANSICOES_ORCAMENTO = {
    'RASCUNHO': {'ENVIADO', 'CANCELADO'},
    'ENVIADO': {'APROVADO', 'REJEITADO', 'CANCELADO'},
}


def dinheiro(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def recalcular_orcamento(orcamento):
    subtotal = sum((item.subtotal for item in orcamento.itens.filter(ativo=True)), Decimal('0'))
    subtotal = dinheiro(subtotal)
    if orcamento.desconto_tipo == 'PERCENTUAL':
        desconto = dinheiro(subtotal * orcamento.desconto_valor / Decimal('100'))
    elif orcamento.desconto_tipo == 'VALOR':
        desconto = dinheiro(orcamento.desconto_valor)
    else:
        desconto = Decimal('0.00')
    total = dinheiro(subtotal - desconto)
    pago = dinheiro(sum((p.valor for p in orcamento.pagamentos.filter(ativo=True)), Decimal('0')))
    if desconto > subtotal:
        raise ValidationError({'desconto_valor': 'Desconto nao pode ser maior que o subtotal.'})
    orcamento.subtotal, orcamento.total, orcamento.valor_pago, orcamento.saldo = (
        subtotal,
        total,
        pago,
        dinheiro(total - pago),
    )
    orcamento.save(update_fields=['subtotal', 'total', 'valor_pago', 'saldo', 'atualizado_em'])
    return orcamento


def transicionar_orcamento(orcamento, destino):
    if destino not in TRANSICOES_ORCAMENTO.get(orcamento.status, set()):
        raise ValidationError({'status': f'Transicao de {orcamento.status} para {destino} nao permitida.'})
    if destino == 'APROVADO' and not orcamento.itens.filter(ativo=True).exists():
        raise ValidationError({'status': 'Orcamento sem itens nao pode ser aprovado.'})
    if destino == 'CANCELADO' and orcamento.pagamentos.filter(ativo=True).exists():
        raise ValidationError({'status': 'Orcamento com pagamentos nao pode ser cancelado.'})
    orcamento.status = destino
    agora = timezone.now()
    if destino == 'APROVADO':
        orcamento.aprovado_em = agora
    if destino == 'REJEITADO':
        orcamento.rejeitado_em = agora
    if destino == 'CANCELADO':
        orcamento.cancelado_em = agora
    orcamento.save()
    return orcamento


def gerar_parcelas(orcamento, quantidade, primeiro_vencimento, intervalo_dias=30):
    if orcamento.status != 'APROVADO':
        raise ValidationError({'status': 'Apenas orcamentos aprovados podem ser parcelados.'})
    if quantidade <= 0:
        raise ValidationError({'quantidade_parcelas': 'Quantidade deve ser maior que zero.'})
    with transaction.atomic():
        orcamento = Orcamento.objects.select_for_update().get(pk=orcamento.pk)
        if orcamento.parcelas.exists() or orcamento.pagamentos.filter(ativo=True).exists():
            raise ValidationError({'parcelas': 'Orcamento ja possui movimentacao financeira.'})
        base = dinheiro(orcamento.total / quantidade)
        valores = [base] * quantidade
        valores[-1] = dinheiro(orcamento.total - sum(valores[:-1], Decimal('0')))
        if any(valor <= 0 for valor in valores):
            raise ValidationError({'quantidade_parcelas': 'Parcelamento gera parcela com valor zero.'})
        for numero, valor in enumerate(valores, 1):
            Parcela.objects.create(
                clinica=orcamento.clinica,
                orcamento=orcamento,
                numero=numero,
                valor=valor,
                vencimento=primeiro_vencimento + timedelta(days=intervalo_dias * (numero - 1)),
            )
    return orcamento


def registrar_pagamento(
    *, orcamento, parcela, valor, forma_pagamento, usuario, observacao='', referencia_externa=None, pago_em=None
):
    with transaction.atomic():
        orcamento = Orcamento.objects.select_for_update().get(pk=orcamento.pk)
        if orcamento.status in {'CANCELADO', 'REJEITADO'}:
            raise ValidationError({'orcamento': 'Orcamento cancelado ou rejeitado nao aceita pagamento.'})
        valor = dinheiro(valor)
        if valor <= 0 or valor > orcamento.saldo:
            raise ValidationError({'valor': 'Valor deve ser maior que zero e nao pode exceder o saldo.'})
        if parcela:
            parcela = Parcela.objects.select_for_update().get(pk=parcela.pk)
            if parcela.orcamento_id != orcamento.id or parcela.status == 'CANCELADA':
                raise ValidationError({'parcela': 'Parcela invalida ou cancelada.'})
            pago_parcela = sum((p.valor for p in parcela.pagamentos.filter(ativo=True)), Decimal('0'))
            if valor > dinheiro(parcela.valor - pago_parcela):
                raise ValidationError({'valor': 'Valor excede o saldo da parcela.'})
        pagamento = Pagamento.objects.create(
            clinica=orcamento.clinica,
            paciente=orcamento.paciente,
            orcamento=orcamento,
            parcela=parcela,
            valor=valor,
            forma_pagamento=forma_pagamento,
            pago_em=pago_em or timezone.now(),
            observacao=observacao,
            referencia_externa=referencia_externa,
            registrado_por=usuario,
        )
        if (
            parcela
            and dinheiro(sum((p.valor for p in parcela.pagamentos.filter(ativo=True)), Decimal('0'))) == parcela.valor
        ):
            parcela.status, parcela.paga_em = 'PAGA', pagamento.pago_em
            parcela.save(update_fields=['status', 'paga_em', 'atualizado_em'])
        recalcular_orcamento(orcamento)
    return pagamento
