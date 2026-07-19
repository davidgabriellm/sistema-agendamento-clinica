import secrets
import uuid
from datetime import date, timedelta

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def caminho_arquivo_clinico(instance, filename):
    """Keep user supplied names out of storage paths and make names unguessable."""
    extensao = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    return (
        f'arquivos-clinicos/clinica-{instance.clinica_id}/paciente-{instance.paciente_id}/{uuid.uuid4().hex}.{extensao}'
    )


class Clinica(models.Model):
    nome = models.CharField(max_length=255)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    cnpj = models.CharField(max_length=18, unique=True, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    timezone = models.CharField(max_length=64, default='America/Maceio')
    antecedencia_minima_cancelamento_horas = models.PositiveSmallIntegerField(default=24)
    duracao_padrao_consulta_minutos = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(1)])
    ativa = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nome) or 'clinica'
            candidato = base[:120]
            contador = 2
            queryset = type(self).objects.all()
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            while queryset.filter(slug=candidato).exists():
                sufixo = f'-{contador}'
                candidato = f'{base[: 120 - len(sufixo)]}{sufixo}'
                contador += 1
            self.slug = candidato
        super().save(*args, **kwargs)


class HorarioFuncionamentoClinica(models.Model):
    DIA_SEGUNDA = 0
    DIA_TERCA = 1
    DIA_QUARTA = 2
    DIA_QUINTA = 3
    DIA_SEXTA = 4
    DIA_SABADO = 5
    DIA_DOMINGO = 6

    DIA_SEMANA_CHOICES = (
        (DIA_SEGUNDA, 'Segunda-feira'),
        (DIA_TERCA, 'Terca-feira'),
        (DIA_QUARTA, 'Quarta-feira'),
        (DIA_QUINTA, 'Quinta-feira'),
        (DIA_SEXTA, 'Sexta-feira'),
        (DIA_SABADO, 'Sabado'),
        (DIA_DOMINGO, 'Domingo'),
    )

    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='horarios_funcionamento')
    dia_semana = models.PositiveSmallIntegerField(choices=DIA_SEMANA_CHOICES)
    horario_inicio = models.TimeField()
    horario_fim = models.TimeField()
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['clinica', 'dia_semana', 'horario_inicio']
        constraints = [
            models.UniqueConstraint(
                fields=['clinica', 'dia_semana', 'horario_inicio', 'horario_fim'],
                name='horario_funcionamento_unico_por_intervalo',
            ),
        ]
        indexes = [
            models.Index(fields=['clinica', 'dia_semana', 'ativo']),
        ]

    def __str__(self):
        return f'{self.clinica} - {self.get_dia_semana_display()} {self.horario_inicio}-{self.horario_fim}'


class BloqueioAgendaClinica(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='bloqueios_agenda')
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    motivo = models.CharField(max_length=255, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['inicio']
        indexes = [
            models.Index(fields=['clinica', 'ativo', 'inicio', 'fim']),
        ]

    def __str__(self):
        return f'{self.clinica} bloqueada de {self.inicio} ate {self.fim}'


class Usuario(AbstractUser):
    TIPO_CHOICES = (
        ('DENTISTA', 'Dentista'),
        ('PACIENTE', 'Paciente'),
        ('ADMIN', 'Administrador'),
    )
    nome_completo = models.CharField(max_length=255)
    nome_preferido = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True)
    cpf = models.CharField(max_length=20, unique=True)
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='usuarios', null=True, blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='PACIENTE')
    telefone = models.CharField(max_length=20)
    data_nascimento = models.DateField(null=True)

    @property
    def idade(self):
        if self.data_nascimento:
            hoje = date.today()
            return (
                hoje.year
                - self.data_nascimento.year
                - ((hoje.month, hoje.day) < (self.data_nascimento.month, self.data_nascimento.day))
            )
        return None

    def get_full_name(self):
        return self.nome_completo or super().get_full_name()

    def get_short_name(self):
        return self.nome_preferido or self.nome_completo or self.username

    def __str__(self):
        return self.get_full_name() or self.username


class Endereco(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='endereco')
    cep = models.CharField(max_length=9, blank=True)
    logradouro = models.CharField(max_length=255, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, blank=True)

    def __str__(self):
        partes = [self.logradouro, self.numero, self.cidade, self.estado]
        return ', '.join([parte for parte in partes if parte])


def gerar_token_convite():
    return secrets.token_urlsafe(32)


def expiracao_padrao_convite():
    return timezone.now() + timedelta(days=7)


class ConviteCadastroPaciente(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='convites_cadastro_paciente')
    token = models.CharField(max_length=64, unique=True, default=gerar_token_convite, editable=False)
    telefone_destino = models.CharField(max_length=20, blank=True)
    email_destino = models.EmailField(blank=True)
    nome_destino = models.CharField(max_length=255, blank=True)
    expira_em = models.DateTimeField(default=expiracao_padrao_convite)
    usado_em = models.DateTimeField(null=True, blank=True)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        related_name='convites_cadastro_criados',
        null=True,
        blank=True,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['clinica', 'ativo', 'expira_em', 'usado_em']),
        ]

    def __str__(self):
        return f'Convite para {self.clinica} ({self.expira_em:%Y-%m-%d %H:%M})'


class Dentista(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='dentistas')
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_dentista')
    especialidade = models.CharField(max_length=100)
    cro = models.CharField(max_length=20, unique=True)
    ativo = models.BooleanField(default=True)
    disponibilidade = models.TextField(blank=True, null=True, help_text='Ex: Seg a Sex, 08h as 18h')

    def __str__(self):
        return f'Dr(a). {self.usuario.get_full_name()} - {self.especialidade}'


class IndisponibilidadeDentista(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='indisponibilidades_dentistas')
    dentista = models.ForeignKey(Dentista, on_delete=models.CASCADE, related_name='indisponibilidades')
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    motivo = models.CharField(max_length=255, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['inicio']
        indexes = [
            models.Index(fields=['clinica', 'dentista', 'ativo', 'inicio', 'fim']),
        ]

    def __str__(self):
        return f'{self.dentista} indisponivel de {self.inicio} ate {self.fim}'


class Procedimento(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='procedimentos')
    nome = models.CharField(max_length=150)
    descricao = models.TextField(blank=True)
    duracao_minutos = models.PositiveSmallIntegerField(default=30)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(fields=['clinica', 'nome'], name='procedimento_nome_unico_por_clinica'),
        ]

    def __str__(self):
        return self.nome


class Agendamento(models.Model):
    STATUS_AGENDADA = 'AGENDADA'
    STATUS_CONFIRMADA = 'CONFIRMADA'
    STATUS_EM_ATENDIMENTO = 'EM_ATENDIMENTO'
    STATUS_CONCLUIDA = 'CONCLUIDA'
    STATUS_CANCELADA = 'CANCELADA'
    STATUS_NAO_COMPARECEU = 'NAO_COMPARECEU'

    STATUS_CHOICES = (
        (STATUS_AGENDADA, 'Agendada'),
        (STATUS_CONFIRMADA, 'Confirmada'),
        (STATUS_EM_ATENDIMENTO, 'Em atendimento'),
        (STATUS_CONCLUIDA, 'Concluida'),
        (STATUS_CANCELADA, 'Cancelada'),
        (STATUS_NAO_COMPARECEU, 'Nao compareceu'),
    )

    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='agendamentos')
    dentista = models.ForeignKey(Dentista, on_delete=models.CASCADE, related_name='agenda')
    paciente = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='meus_agendamentos')
    procedimento = models.CharField(max_length=150)
    procedimento_ref = models.ForeignKey(
        Procedimento, on_delete=models.PROTECT, related_name='agendamentos', null=True, blank=True
    )

    data_horario = models.DateTimeField(help_text='Data e hora da consulta')
    data_hora_fim = models.DateTimeField(null=True, blank=True)
    duracao_minutos = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AGENDADA)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data_horario']
        indexes = [
            models.Index(fields=['dentista', 'data_horario']),
            models.Index(fields=['clinica', 'status']),
        ]

    def __str__(self):
        return f'{self.paciente} com {self.dentista} em {self.data_horario}'


class ProntuarioPaciente(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='prontuarios')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='prontuarios')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        related_name='prontuarios_criados',
        null=True,
        blank=True,
    )
    atualizado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        related_name='prontuarios_atualizados',
        null=True,
        blank=True,
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['paciente__nome_completo']
        constraints = [
            models.UniqueConstraint(fields=['clinica', 'paciente'], name='prontuario_unico_por_clinica_paciente'),
        ]
        indexes = [models.Index(fields=['clinica', 'paciente', 'ativo'])]

    def __str__(self):
        return f'Prontuario de {self.paciente} - {self.clinica}'


class Anamnese(models.Model):
    prontuario = models.OneToOneField(ProntuarioPaciente, on_delete=models.PROTECT, related_name='anamnese')
    alergias = models.TextField(blank=True)
    medicamentos_em_uso = models.TextField(blank=True)
    condicoes_medicas = models.TextField(blank=True)
    cirurgias_anteriores = models.TextField(blank=True)
    historico_familiar = models.TextField(blank=True)
    gestante = models.BooleanField(null=True, blank=True)
    fumante = models.BooleanField(null=True, blank=True)
    consumo_alcool = models.BooleanField(null=True, blank=True)
    observacoes = models.TextField(blank=True)
    preenchida_em = models.DateTimeField(auto_now_add=True)
    preenchida_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, related_name='anamneses_preenchidas', null=True, blank=True
    )
    atualizada_em = models.DateTimeField(auto_now=True)
    atualizada_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, related_name='anamneses_atualizadas', null=True, blank=True
    )

    def __str__(self):
        return f'Anamnese de {self.prontuario.paciente}'


class EvolucaoClinica(models.Model):
    prontuario = models.ForeignKey(ProntuarioPaciente, on_delete=models.PROTECT, related_name='evolucoes')
    agendamento = models.ForeignKey(Agendamento, on_delete=models.PROTECT, related_name='evolucoes_clinicas')
    dentista = models.ForeignKey(Dentista, on_delete=models.PROTECT, related_name='evolucoes_clinicas')
    descricao = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, related_name='evolucoes_criadas', null=True, blank=True
    )

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['prontuario', 'criado_em']),
            models.Index(fields=['agendamento', 'dentista']),
        ]

    def __str__(self):
        return f'Evolucao de {self.prontuario.paciente} em {self.criado_em:%Y-%m-%d}'


class Odontograma(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='odontogramas')
    prontuario = models.ForeignKey(ProntuarioPaciente, on_delete=models.PROTECT, related_name='odontogramas')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name='odontogramas_criados')
    atualizado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='odontogramas_atualizados'
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['prontuario__paciente__nome_completo']
        constraints = [
            models.UniqueConstraint(fields=['prontuario', 'ativo'], name='odontograma_ativo_unico_por_prontuario')
        ]


class RegistroOdontograma(models.Model):
    FACE_CHOICES = [
        (valor, valor.replace('_', ' ').title())
        for valor in ('VESTIBULAR', 'LINGUAL', 'PALATINA', 'MESIAL', 'DISTAL', 'OCLUSAL', 'INCISAL', 'GERAL')
    ]
    CONDICAO_CHOICES = [
        (valor, valor.replace('_', ' ').title())
        for valor in (
            'SAUDAVEL',
            'CARIE',
            'RESTAURADO',
            'AUSENTE',
            'FRATURADO',
            'IMPLANTE',
            'COROA',
            'TRATAMENTO_CANAL',
            'EXTRACAO_INDICADA',
            'PROTESE',
            'OUTRO',
        )
    ]
    odontograma = models.ForeignKey(Odontograma, on_delete=models.PROTECT, related_name='registros')
    numero_dente = models.PositiveSmallIntegerField()
    face = models.CharField(max_length=20, choices=FACE_CHOICES)
    condicao = models.CharField(max_length=25, choices=CONDICAO_CHOICES)
    observacao = models.TextField(blank=True)
    dentista = models.ForeignKey(Dentista, on_delete=models.PROTECT, related_name='registros_odontograma')
    criado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='registros_odontograma_criados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-criado_em']


class PlanoTratamento(models.Model):
    STATUS_CHOICES = [
        (v, v.replace('_', ' ').title())
        for v in ('RASCUNHO', 'PROPOSTO', 'APROVADO', 'EM_ANDAMENTO', 'CONCLUIDO', 'CANCELADO')
    ]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='planos_tratamento')
    prontuario = models.ForeignKey(ProntuarioPaciente, on_delete=models.PROTECT, related_name='planos_tratamento')
    titulo = models.CharField(max_length=150)
    descricao = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RASCUNHO')
    criado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='planos_tratamento_criados'
    )
    aprovado_em = models.DateTimeField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-criado_em']


class ItemPlanoTratamento(models.Model):
    STATUS_CHOICES = [(v, v.replace('_', ' ').title()) for v in ('PENDENTE', 'EM_ANDAMENTO', 'CONCLUIDO', 'CANCELADO')]
    PRIORIDADE_CHOICES = [(v, v.title()) for v in ('BAIXA', 'MEDIA', 'ALTA', 'URGENTE')]
    plano = models.ForeignKey(PlanoTratamento, on_delete=models.PROTECT, related_name='itens')
    procedimento_ref = models.ForeignKey(
        Procedimento, on_delete=models.PROTECT, null=True, blank=True, related_name='itens_plano'
    )
    descricao = models.TextField()
    numero_dente = models.PositiveSmallIntegerField(null=True, blank=True)
    face = models.CharField(max_length=20, choices=RegistroOdontograma.FACE_CHOICES, null=True, blank=True)
    prioridade = models.CharField(max_length=10, choices=PRIORIDADE_CHOICES, default='MEDIA')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    quantidade = models.PositiveSmallIntegerField(default=1)
    valor_estimado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ordem', 'id']


class Orcamento(models.Model):
    STATUS_CHOICES = [(v, v.title()) for v in ('RASCUNHO', 'ENVIADO', 'APROVADO', 'REJEITADO', 'CANCELADO', 'VENCIDO')]
    DESCONTO_CHOICES = [(v, v.title()) for v in ('NENHUM', 'VALOR', 'PERCENTUAL')]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='orcamentos')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='orcamentos')
    plano_tratamento = models.ForeignKey(
        PlanoTratamento, on_delete=models.PROTECT, null=True, blank=True, related_name='orcamentos'
    )
    titulo = models.CharField(max_length=150)
    descricao = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RASCUNHO')
    validade_em = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    desconto_tipo = models.CharField(max_length=12, choices=DESCONTO_CHOICES, default='NENHUM')
    desconto_valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    saldo = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    criado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name='orcamentos_criados')
    aprovado_em = models.DateTimeField(null=True, blank=True)
    rejeitado_em = models.DateTimeField(null=True, blank=True)
    cancelado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [models.Index(fields=['clinica', 'paciente', 'status'])]


class ItemOrcamento(models.Model):
    orcamento = models.ForeignKey(Orcamento, on_delete=models.PROTECT, related_name='itens')
    item_plano_tratamento = models.ForeignKey(
        ItemPlanoTratamento, on_delete=models.PROTECT, null=True, blank=True, related_name='itens_orcamento'
    )
    procedimento_ref = models.ForeignKey(
        Procedimento, on_delete=models.PROTECT, null=True, blank=True, related_name='itens_orcamento'
    )
    descricao = models.TextField()
    quantidade = models.PositiveSmallIntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    numero_dente = models.PositiveSmallIntegerField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['id']


class Parcela(models.Model):
    STATUS_CHOICES = [(v, v.title()) for v in ('PENDENTE', 'PAGA', 'VENCIDA', 'CANCELADA')]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='parcelas')
    orcamento = models.ForeignKey(Orcamento, on_delete=models.PROTECT, related_name='parcelas')
    numero = models.PositiveSmallIntegerField()
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    vencimento = models.DateField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='PENDENTE')
    paga_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['numero']
        constraints = [
            models.UniqueConstraint(fields=['orcamento', 'numero'], name='parcela_numero_unico_por_orcamento')
        ]


class Pagamento(models.Model):
    FORMAS_CHOICES = [
        (v, v.replace('_', ' ').title())
        for v in ('DINHEIRO', 'PIX', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'TRANSFERENCIA', 'OUTRO')
    ]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='pagamentos')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='pagamentos')
    orcamento = models.ForeignKey(Orcamento, on_delete=models.PROTECT, related_name='pagamentos')
    parcela = models.ForeignKey(Parcela, on_delete=models.PROTECT, null=True, blank=True, related_name='pagamentos')
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    forma_pagamento = models.CharField(max_length=20, choices=FORMAS_CHOICES)
    pago_em = models.DateTimeField(default=timezone.now)
    observacao = models.TextField(blank=True)
    referencia_externa = models.CharField(max_length=100, blank=True, null=True)
    registrado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='pagamentos_registrados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-pago_em', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['clinica', 'referencia_externa'],
                condition=models.Q(referencia_externa__isnull=False),
                name='pagamento_referencia_unica_por_clinica',
            )
        ]


class ArquivoClinico(models.Model):
    CATEGORIA_CHOICES = [
        (v, v.title())
        for v in ('RADIOGRAFIA', 'EXAME', 'FOTOGRAFIA', 'DOCUMENTO', 'RECEITA', 'ATESTADO', 'CONSENTIMENTO', 'OUTRO')
    ]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='arquivos_clinicos')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='arquivos_clinicos')
    prontuario = models.ForeignKey(
        ProntuarioPaciente, on_delete=models.PROTECT, null=True, blank=True, related_name='arquivos_clinicos'
    )
    agendamento = models.ForeignKey(
        Agendamento, on_delete=models.PROTECT, null=True, blank=True, related_name='arquivos_clinicos'
    )
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    arquivo = models.FileField(upload_to=caminho_arquivo_clinico)
    nome_original = models.CharField(max_length=255, editable=False)
    nome_exibicao = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, editable=False)
    tamanho_bytes = models.PositiveBigIntegerField(editable=False)
    descricao = models.TextField(blank=True)
    hash_sha256 = models.CharField(max_length=64, editable=False)
    liberado_paciente = models.BooleanField(default=True)
    enviado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='arquivos_clinicos_enviados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [models.Index(fields=['clinica', 'paciente', 'ativo'])]


class AcessoArquivoClinico(models.Model):
    ACAO_CHOICES = [(v, v.title()) for v in ('VISUALIZACAO', 'DOWNLOAD', 'DESATIVACAO', 'EXPORTACAO')]
    arquivo = models.ForeignKey(ArquivoClinico, on_delete=models.PROTECT, related_name='acessos')
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name='acessos_arquivos_clinicos')
    acao = models.CharField(max_length=20, choices=ACAO_CHOICES)
    data_hora = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    sucesso = models.BooleanField(default=True)

    class Meta:
        ordering = ['-data_hora']


class TermoConsentimento(models.Model):
    clinica = models.ForeignKey(
        Clinica, on_delete=models.CASCADE, null=True, blank=True, related_name='termos_consentimento'
    )
    titulo = models.CharField(max_length=255)
    codigo = models.SlugField(max_length=100)
    versao = models.PositiveIntegerField()
    conteudo = models.TextField()
    finalidade = models.TextField(blank=True)
    obrigatorio = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)
    publicado_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='termos_consentimento_criados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['codigo', '-versao']
        constraints = [models.UniqueConstraint(fields=['codigo', 'versao'], name='termo_codigo_versao_unico')]


class ConsentimentoPaciente(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='consentimentos_pacientes')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='consentimentos')
    termo = models.ForeignKey(TermoConsentimento, on_delete=models.PROTECT, related_name='aceites')
    aceito = models.BooleanField(default=True)
    aceito_em = models.DateTimeField(default=timezone.now)
    revogado_em = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    registrado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='consentimentos_registrados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-aceito_em']


class SolicitacaoAnonimizacao(models.Model):
    STATUS_CHOICES = [(v, v.title()) for v in ('SOLICITADA', 'EM_ANALISE', 'PROCESSADA', 'RECUSADA')]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='solicitacoes_anonimizacao')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='solicitacoes_anonimizacao')
    motivo = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SOLICITADA')
    solicitado_em = models.DateTimeField(auto_now_add=True)
    processado_em = models.DateTimeField(null=True, blank=True)
    processado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='anonimizacoes_processadas'
    )

    class Meta:
        ordering = ['-solicitado_em']


class TemplateMensagem(models.Model):
    CANAL_CHOICES = [(v, v.title()) for v in ('WHATSAPP', 'EMAIL', 'SMS', 'PUSH', 'INTERNO')]
    clinica = models.ForeignKey(
        Clinica, on_delete=models.CASCADE, null=True, blank=True, related_name='templates_mensagem'
    )
    nome = models.CharField(max_length=150)
    codigo = models.SlugField(max_length=100)
    canal = models.CharField(max_length=12, choices=CANAL_CHOICES)
    versao = models.PositiveIntegerField(default=1)
    assunto = models.CharField(max_length=255, blank=True)
    corpo = models.TextField()
    ativo = models.BooleanField(default=True)
    publicado_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, related_name='templates_mensagem_criados'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['codigo', '-versao']
        constraints = [models.UniqueConstraint(fields=['codigo', 'versao'], name='template_codigo_versao_unico')]


class PreferenciaComunicacao(models.Model):
    paciente = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='preferencias_comunicacao')
    aceita_whatsapp = models.BooleanField(default=True)
    aceita_email = models.BooleanField(default=True)
    aceita_sms = models.BooleanField(default=False)
    aceita_push = models.BooleanField(default=False)
    aceita_marketing = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['paciente_id']


class Notificacao(models.Model):
    CANAL_CHOICES = TemplateMensagem.CANAL_CHOICES
    STATUS_CHOICES = [(v, v.title()) for v in ('PENDENTE', 'PROCESSANDO', 'ENVIADA', 'ERRO', 'CANCELADA')]
    clinica = models.ForeignKey(Clinica, on_delete=models.PROTECT, related_name='notificacoes')
    paciente = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='notificacoes')
    agendamento = models.ForeignKey(
        Agendamento, on_delete=models.PROTECT, null=True, blank=True, related_name='notificacoes'
    )
    orcamento = models.ForeignKey(
        Orcamento, on_delete=models.PROTECT, null=True, blank=True, related_name='notificacoes'
    )
    template = models.ForeignKey(
        TemplateMensagem, on_delete=models.PROTECT, null=True, blank=True, related_name='notificacoes'
    )
    canal = models.CharField(max_length=12, choices=CANAL_CHOICES)
    assunto = models.CharField(max_length=255, blank=True)
    mensagem = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDENTE')
    erro = models.TextField(blank=True)
    agendada_para = models.DateTimeField()
    enviada_em = models.DateTimeField(null=True, blank=True)
    criada_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name='notificacoes_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['agendada_para', 'id']
        indexes = [models.Index(fields=['clinica', 'paciente', 'status', 'agendada_para'])]


class EventoNotificacao(models.Model):
    ACAO_CHOICES = [(v, v.title()) for v in ('CRIACAO', 'CANCELAMENTO', 'CONFIRMACAO', 'TENTATIVA_ENVIO', 'ERRO_ENVIO')]
    notificacao = models.ForeignKey(Notificacao, on_delete=models.PROTECT, related_name='eventos')
    usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos_notificacao'
    )
    acao = models.CharField(max_length=20, choices=ACAO_CHOICES)
    detalhes = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
