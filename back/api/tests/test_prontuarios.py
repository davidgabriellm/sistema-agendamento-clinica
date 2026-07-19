from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Agendamento, Anamnese, Clinica, Dentista, EvolucaoClinica, ProntuarioPaciente, Usuario


def criar_usuario(username, cpf, email, *, clinica=None, tipo='PACIENTE', is_staff=False):
    return Usuario.objects.create_user(
        username=username,
        password='SenhaAtual123!',
        nome_completo=username.replace('_', ' ').title(),
        email=email,
        cpf=cpf,
        telefone='82999990000',
        data_nascimento='1990-01-01',
        clinica=clinica,
        tipo=tipo,
        is_staff=is_staff,
    )


class ProntuarioApiTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(nome='Clinica Prontuario A')
        self.clinica_b = Clinica.objects.create(nome='Clinica Prontuario B')
        self.staff = criar_usuario(
            'staff_prontuario', '81000000001', 'staff.prontuario@example.com', is_staff=True, tipo='ADMIN'
        )
        self.paciente_a = criar_usuario(
            'paciente_prontuario_a', '81000000002', 'paciente.a@example.com', clinica=self.clinica_a
        )
        self.paciente_b = criar_usuario(
            'paciente_prontuario_b', '81000000003', 'paciente.b@example.com', clinica=self.clinica_b
        )
        self.usuario_dentista_a = criar_usuario(
            'dentista_prontuario_a', '81000000004', 'dentista.a@example.com', clinica=self.clinica_a, tipo='DENTISTA'
        )
        self.usuario_dentista_b = criar_usuario(
            'dentista_prontuario_b', '81000000005', 'dentista.b@example.com', clinica=self.clinica_b, tipo='DENTISTA'
        )
        self.dentista_a = Dentista.objects.create(
            clinica=self.clinica_a, usuario=self.usuario_dentista_a, especialidade='Clinico', cro='81001-AL'
        )
        self.dentista_b = Dentista.objects.create(
            clinica=self.clinica_b, usuario=self.usuario_dentista_b, especialidade='Clinico', cro='81002-AL'
        )
        self.prontuario_a = ProntuarioPaciente.objects.create(
            clinica=self.clinica_a, paciente=self.paciente_a, criado_por=self.staff
        )
        self.prontuario_b = ProntuarioPaciente.objects.create(
            clinica=self.clinica_b, paciente=self.paciente_b, criado_por=self.staff
        )

    def agendamento(
        self, *, status_agendamento=Agendamento.STATUS_EM_ATENDIMENTO, paciente=None, dentista=None, clinica=None
    ):
        clinica = clinica or self.clinica_a
        dentista = dentista or self.dentista_a
        paciente = paciente or self.paciente_a
        inicio = timezone.now() + timedelta(days=1)
        return Agendamento.objects.create(
            clinica=clinica,
            dentista=dentista,
            paciente=paciente,
            procedimento='Consulta',
            data_horario=inicio,
            data_hora_fim=inicio + timedelta(minutes=30),
            duracao_minutos=30,
            status=status_agendamento,
        )

    def test_staff_cria_prontuario_e_rejeita_duplicado_ou_paciente_outra_clinica(self):
        novo = criar_usuario('paciente_novo', '81000000006', 'paciente.novo@example.com', clinica=self.clinica_a)
        self.client.force_authenticate(self.staff)
        criado = self.client.post(
            '/api/v1/prontuarios/', {'clinica': self.clinica_a.id, 'paciente': novo.id}, format='json'
        )
        duplicado = self.client.post(
            '/api/v1/prontuarios/', {'clinica': self.clinica_a.id, 'paciente': novo.id}, format='json'
        )
        outra_clinica = self.client.post(
            '/api/v1/prontuarios/', {'clinica': self.clinica_a.id, 'paciente': self.paciente_b.id}, format='json'
        )

        self.assertEqual(criado.status_code, status.HTTP_201_CREATED)
        self.assertEqual(criado.data['clinica'], self.clinica_a.id)
        self.assertEqual(ProntuarioPaciente.objects.get(pk=criado.data['id']).criado_por, self.staff)
        self.assertEqual(duplicado.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(outra_clinica.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paciente_nao_cria_nem_acessa_prontuario_de_outro_paciente(self):
        self.client.force_authenticate(self.paciente_a)
        criacao = self.client.post(
            '/api/v1/prontuarios/', {'clinica': self.clinica_a.id, 'paciente': self.paciente_a.id}, format='json'
        )
        outro = self.client.get(reverse('prontuario-detail', args=[self.prontuario_b.id]))

        self.assertEqual(criacao.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(outro.status_code, status.HTTP_404_NOT_FOUND)

    def test_anamnese_e_criada_atualizada_por_dentista_e_paciente_nao_altera(self):
        url = reverse('prontuario-anamnese', args=[self.prontuario_a.id])
        self.client.force_authenticate(self.usuario_dentista_a)
        criada = self.client.patch(url, {'alergias': 'Penicilina', 'fumante': False}, format='json')
        atualizada = self.client.patch(url, {'medicamentos_em_uso': 'Nenhum'}, format='json')

        self.assertEqual(criada.status_code, status.HTTP_200_OK)
        self.assertEqual(atualizada.status_code, status.HTTP_200_OK)
        anamnese = Anamnese.objects.get(prontuario=self.prontuario_a)
        self.assertEqual(anamnese.preenchida_por, self.usuario_dentista_a)
        self.assertEqual(anamnese.atualizada_por, self.usuario_dentista_a)

        self.client.force_authenticate(self.paciente_a)
        proibida = self.client.patch(url, {'alergias': 'Tentativa'}, format='json')
        self.assertEqual(proibida.status_code, status.HTTP_403_FORBIDDEN)

    def test_dentista_outra_clinica_recebe_404(self):
        self.client.force_authenticate(self.usuario_dentista_b)
        self.assertEqual(
            self.client.get(reverse('prontuario-detail', args=[self.prontuario_a.id])).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_evolucao_permite_em_atendimento_e_concluida_e_protege_vinculos(self):
        self.client.force_authenticate(self.usuario_dentista_a)
        em_atendimento = self.agendamento()
        concluida = self.agendamento(status_agendamento=Agendamento.STATUS_CONCLUIDA)
        url = '/api/v1/evolucoes-clinicas/'
        primeira = self.client.post(
            url,
            {
                'prontuario': self.prontuario_a.id,
                'agendamento': em_atendimento.id,
                'descricao': 'Paciente em atendimento.',
            },
            format='json',
        )
        segunda = self.client.post(
            url,
            {'prontuario': self.prontuario_a.id, 'agendamento': concluida.id, 'descricao': 'Atendimento concluido.'},
            format='json',
        )

        self.assertEqual(primeira.status_code, status.HTTP_201_CREATED)
        self.assertEqual(segunda.status_code, status.HTTP_201_CREATED)
        evolucao = EvolucaoClinica.objects.get(pk=primeira.data['id'])
        self.assertEqual(evolucao.dentista, self.dentista_a)
        self.assertEqual(evolucao.criado_por, self.usuario_dentista_a)
        imutavel = self.client.patch(
            reverse('evolucao-clinica-detail', args=[evolucao.id]), {'dentista': self.dentista_b.id}, format='json'
        )
        self.assertEqual(imutavel.status_code, status.HTTP_400_BAD_REQUEST)

    def test_evolucao_rejeita_status_inadequado_e_atendimento_de_outro_dentista(self):
        self.client.force_authenticate(self.usuario_dentista_a)
        agendada = self.agendamento(status_agendamento=Agendamento.STATUS_AGENDADA)
        outro_dentista = self.agendamento(dentista=self.dentista_b, clinica=self.clinica_b, paciente=self.paciente_b)
        url = '/api/v1/evolucoes-clinicas/'
        invalida = self.client.post(
            url,
            {'prontuario': self.prontuario_a.id, 'agendamento': agendada.id, 'descricao': 'Nao permitido'},
            format='json',
        )
        outra = self.client.post(
            url,
            {'prontuario': self.prontuario_a.id, 'agendamento': outro_dentista.id, 'descricao': 'Nao permitido'},
            format='json',
        )

        self.assertEqual(invalida.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(outra.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paciente_nao_cria_nem_apaga_evolucao(self):
        evolucao = EvolucaoClinica.objects.create(
            prontuario=self.prontuario_a,
            agendamento=self.agendamento(),
            dentista=self.dentista_a,
            descricao='Registro clinico',
            criado_por=self.usuario_dentista_a,
        )
        self.client.force_authenticate(self.paciente_a)
        criacao = self.client.post(
            '/api/v1/evolucoes-clinicas/',
            {'prontuario': self.prontuario_a.id, 'agendamento': evolucao.agendamento_id, 'descricao': 'Tentativa'},
            format='json',
        )
        exclusao = self.client.delete(reverse('evolucao-clinica-detail', args=[evolucao.id]))

        self.assertEqual(criacao.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(exclusao.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
