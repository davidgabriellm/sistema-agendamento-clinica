from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

class Usuario(AbstractUser): 
    TIPO_CHOICES = (
        ('MEDICO', 'Médico'),
        ('PACIENTE', 'Paciente'),
        ('ADMIN', 'Administrador'),
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='PACIENTE')
    telefone = models.CharField(max_length=20, blank=True, null=True)


class Medico(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_medico')
    especialidade = models.CharField(max_length=100)
    crm = models.CharField(max_length=20, unique=True)
    ativo = models.BooleanField(default=True)
    disponibilidade = models.TextField(blank=True, null=True, help_text="Ex: Seg a Sex, 08h as 18h")

    def __str__(self):
        return f"Dr(a). {self.usuario.get_full_name()} - {self.especialidade}"
    

class Agendamento(models.Model):
    STATUS_CHOICES = (
        ('AGENDADO', 'Agendado'),
        ('CANCELADO', 'Cancelado'),
        ('CONCLUIDO', 'Concluído'),
    )

    medico = models.ForeignKey(Medico, on_delete=models.CASCADE, related_name='agenda')
    paciente = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='meus_agendamentos')

    data_horario = models.DateTimeField(help_text="Data e hora da consulta")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AGENDADO')

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('medico', 'data_horario')  # Garante que um médico não tenha dois agendamentos no mesmo horário
        ordering = ['data_horario']

    def __str__(self):
        return f"{self.paciente} com {self.medico} em {self.data_horario}"