from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Agendamento, Clinica, Dentista, Notificacao, Usuario
from api.services_notification import cancelar_notificacoes, criar_lembrete_consulta


def criar_usuario(username, cpf, email, clinica, tipo='PACIENTE', staff=False):
    return Usuario.objects.create_user(
        username=username,
        password='SenhaAtual123!',
        nome_completo=username,
        email=email,
        cpf=cpf,
        telefone='82999990000',
        data_nascimento='1990-01-01',
        clinica=clinica,
        tipo=tipo,
        is_staff=staff,
    )


class NotificacaoApiTest(APITestCase):
    def setUp(self):
        self.clinica = Clinica.objects.create(nome='Clinica Notificacoes')
        self.outra = Clinica.objects.create(nome='Outra Notificacoes')
        self.staff = criar_usuario('staff_notif', '96000000001', 'staff.notif@example.com', self.clinica, 'ADMIN', True)
        self.paciente = criar_usuario('paciente_notif', '96000000002', 'paciente.notif@example.com', self.clinica)
        self.outro = criar_usuario('outro_notif', '96000000003', 'outro.notif@example.com', self.outra)
        self.dentista_usuario = criar_usuario(
            'dentista_notif', '96000000004', 'dentista.notif@example.com', self.clinica, 'DENTISTA'
        )
        self.dentista = Dentista.objects.create(
            clinica=self.clinica, usuario=self.dentista_usuario, especialidade='Clinico', cro='96001-AL'
        )
        inicio = timezone.now() + timedelta(days=3)
        self.agendamento = Agendamento.objects.create(
            clinica=self.clinica,
            paciente=self.paciente,
            dentista=self.dentista,
            procedimento='Consulta',
            data_horario=inicio,
            data_hora_fim=inicio + timedelta(minutes=30),
            duracao_minutos=30,
        )

    def test_lembretes_cancelamento_reagendamento_e_confirmacao(self):
        self.assertEqual(len(criar_lembrete_consulta(self.agendamento, self.staff)), 2)
        self.assertEqual(Notificacao.objects.filter(agendamento=self.agendamento, status='PENDENTE').count(), 2)
        self.assertEqual(cancelar_notificacoes(self.agendamento, self.staff), 2)
        self.assertEqual(Notificacao.objects.filter(agendamento=self.agendamento, status='CANCELADA').count(), 2)
        criar_lembrete_consulta(self.agendamento, self.staff)
        self.client.force_authenticate(self.staff)
        resposta = self.client.post(f'/api/v1/agendamentos/{self.agendamento.id}/confirmar-presenca/')
        self.assertEqual(resposta.status_code, status.HTTP_200_OK)
        self.assertEqual(resposta.data['status'], 'CONFIRMADA')
        self.client.force_authenticate(self.paciente)
        self.assertEqual(self.client.get('/api/v1/notificacoes/').data['count'], 4)

    def test_templates_preferencias_e_isolamento(self):
        self.client.force_authenticate(self.staff)
        template = self.client.post(
            '/api/v1/templates-mensagem/',
            {'nome': 'Lembrete', 'codigo': 'lembrete-consulta', 'canal': 'WHATSAPP', 'versao': 1, 'corpo': 'Consulta'},
            format='json',
        )
        self.assertEqual(template.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.client.post(
                '/api/v1/templates-mensagem/',
                {
                    'nome': 'Duplicado',
                    'codigo': 'lembrete-consulta',
                    'canal': 'WHATSAPP',
                    'versao': 1,
                    'corpo': 'Consulta',
                },
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.client.force_authenticate(self.paciente)
        preferencias = self.client.get('/api/v1/preferencias-comunicacao/')
        self.assertEqual(preferencias.status_code, status.HTTP_200_OK)
        self.assertEqual(len(preferencias.data['results']), 1)
        preferencia_id = preferencias.data['results'][0]['id']
        self.assertEqual(
            self.client.patch(
                f'/api/v1/preferencias-comunicacao/{preferencia_id}/', {'aceita_whatsapp': False}, format='json'
            ).status_code,
            status.HTTP_200_OK,
        )
        criar_lembrete_consulta(self.agendamento, self.staff)
        self.assertEqual(self.client.get('/api/v1/notificacoes/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(f'/api/v1/usuarios/{self.outro.id}/').status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get('/api/v1/notificacoes/').data['count'], 0)
