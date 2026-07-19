from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Clinica, Dentista, Procedimento, ProntuarioPaciente, Usuario


def usuario(username, cpf, email, *, clinica=None, tipo='PACIENTE', is_staff=False):
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
        is_staff=is_staff,
    )


class OdontogramaPlanoTest(APITestCase):
    def setUp(self):
        self.a, self.b = Clinica.objects.create(nome='Clinica A'), Clinica.objects.create(nome='Clinica B')
        self.paciente = usuario('paciente_odont', '91000000001', 'p@a.test', clinica=self.a)
        self.outro = usuario('paciente_b', '91000000002', 'p@b.test', clinica=self.b)
        self.dentista_user = usuario('dentista_odont', '91000000003', 'd@a.test', clinica=self.a, tipo='DENTISTA')
        self.dentista_b_user = usuario('dentista_b', '91000000004', 'd@b.test', clinica=self.b, tipo='DENTISTA')
        self.dentista = Dentista.objects.create(
            clinica=self.a, usuario=self.dentista_user, especialidade='Clinico', cro='91001-AL'
        )
        self.dentista_b = Dentista.objects.create(
            clinica=self.b, usuario=self.dentista_b_user, especialidade='Clinico', cro='91002-AL'
        )
        self.prontuario = ProntuarioPaciente.objects.create(clinica=self.a, paciente=self.paciente)
        self.prontuario_b = ProntuarioPaciente.objects.create(clinica=self.b, paciente=self.outro)
        self.procedimento = Procedimento.objects.create(clinica=self.a, nome='Restauracao')
        self.procedimento_b = Procedimento.objects.create(clinica=self.b, nome='Outro')

    def odontograma(self):
        return self.client.post('/api/v1/odontogramas/', {'prontuario': self.prontuario.id}, format='json')

    def test_fluxo_historico_plano_e_transicoes(self):
        self.client.force_authenticate(self.dentista_user)
        odontograma = self.odontograma()
        self.assertEqual(odontograma.status_code, status.HTTP_201_CREATED)
        primeiro = self.client.post(
            '/api/v1/registros-odontograma/',
            {'odontograma': odontograma.data['id'], 'numero_dente': 11, 'face': 'VESTIBULAR', 'condicao': 'CARIE'},
            format='json',
        )
        segundo = self.client.post(
            '/api/v1/registros-odontograma/',
            {'odontograma': odontograma.data['id'], 'numero_dente': 11, 'face': 'VESTIBULAR', 'condicao': 'RESTAURADO'},
            format='json',
        )
        plano = self.client.post(
            '/api/v1/planos-tratamento/', {'prontuario': self.prontuario.id, 'titulo': 'Plano inicial'}, format='json'
        )
        item = self.client.post(
            '/api/v1/itens-plano-tratamento/',
            {
                'plano': plano.data['id'],
                'procedimento_ref': self.procedimento.id,
                'descricao': 'Restaurar',
                'quantidade': 1,
            },
            format='json',
        )
        for acao in ('propor', 'aprovar', 'iniciar', 'concluir'):
            self.assertEqual(
                self.client.post(f'/api/v1/planos-tratamento/{plano.data["id"]}/{acao}/').status_code,
                status.HTTP_200_OK,
            )
        bloqueado = self.client.post(
            '/api/v1/itens-plano-tratamento/', {'plano': plano.data['id'], 'descricao': 'Novo'}, format='json'
        )
        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 201)
        self.assertEqual(item.status_code, 201)
        self.assertEqual(self.client.get('/api/v1/registros-odontograma/').data['count'], 2)
        self.assertEqual(bloqueado.status_code, 400)

    def test_invalidos_permissoes_e_isolamento(self):
        self.client.force_authenticate(self.dentista_user)
        odonto = self.odontograma()
        self.assertEqual(self.odontograma().status_code, 400)
        self.assertEqual(
            self.client.post(
                '/api/v1/registros-odontograma/',
                {'odontograma': odonto.data['id'], 'numero_dente': 10, 'face': 'X', 'condicao': 'X'},
                format='json',
            ).status_code,
            400,
        )
        plano = self.client.post(
            '/api/v1/planos-tratamento/', {'prontuario': self.prontuario.id, 'titulo': 'P'}, format='json'
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/itens-plano-tratamento/',
                {'plano': plano.data['id'], 'descricao': 'x', 'quantidade': 0},
                format='json',
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/itens-plano-tratamento/',
                {'plano': plano.data['id'], 'descricao': 'x', 'procedimento_ref': self.procedimento_b.id},
                format='json',
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/planos-tratamento/', {'prontuario': self.prontuario_b.id, 'titulo': 'invasao'}, format='json'
            ).status_code,
            400,
        )
        self.client.force_authenticate(self.paciente)
        self.assertEqual(
            self.client.post('/api/v1/odontogramas/', {'prontuario': self.prontuario.id}, format='json').status_code,
            403,
        )
        self.assertEqual(self.client.get('/api/v1/odontogramas/').data['count'], 1)
