from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Clinica, Dentista, Orcamento, Usuario


def criar_usuario(username, cpf, email, *, clinica=None, tipo='PACIENTE', is_staff=False):
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


class FinanceiroApiTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(nome='Clinica Financeira A')
        self.clinica_b = Clinica.objects.create(nome='Clinica Financeira B')
        self.staff = criar_usuario('staff_fin', '93000000001', 'staff.fin@example.com', tipo='ADMIN', is_staff=True)
        self.paciente = criar_usuario('paciente_fin', '93000000002', 'paciente.fin@example.com', clinica=self.clinica_a)
        self.outro_paciente = criar_usuario(
            'paciente_fin_b', '93000000003', 'paciente.finb@example.com', clinica=self.clinica_b
        )
        self.dentista_usuario = criar_usuario(
            'dentista_fin', '93000000004', 'dentista.fin@example.com', clinica=self.clinica_a, tipo='DENTISTA'
        )
        self.dentista_b_usuario = criar_usuario(
            'dentista_fin_b', '93000000005', 'dentista.finb@example.com', clinica=self.clinica_b, tipo='DENTISTA'
        )
        Dentista.objects.create(
            clinica=self.clinica_a, usuario=self.dentista_usuario, especialidade='Clinico', cro='93001-AL'
        )
        Dentista.objects.create(
            clinica=self.clinica_b, usuario=self.dentista_b_usuario, especialidade='Clinico', cro='93002-AL'
        )

    def criar_orcamento_com_item(self, desconto_tipo='NENHUM', desconto_valor='0.00'):
        self.client.force_authenticate(self.staff)
        orcamento = self.client.post(
            '/api/v1/orcamentos/',
            {
                'paciente': self.paciente.id,
                'titulo': 'Tratamento',
                'desconto_tipo': desconto_tipo,
                'desconto_valor': desconto_valor,
                'total': '999.00',
            },
            format='json',
        )
        self.assertEqual(orcamento.status_code, status.HTTP_201_CREATED)
        item = self.client.post(
            '/api/v1/itens-orcamento/',
            {
                'orcamento': orcamento.data['id'],
                'descricao': 'Procedimento',
                'quantidade': 2,
                'valor_unitario': '50.00',
                'subtotal': '0.01',
            },
            format='json',
        )
        self.assertEqual(item.status_code, status.HTTP_201_CREATED)
        return orcamento.data['id']

    def aprovar(self, orcamento_id):
        self.assertEqual(self.client.post(f'/api/v1/orcamentos/{orcamento_id}/enviar/').status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(f'/api/v1/orcamentos/{orcamento_id}/aprovar/').status_code, status.HTTP_200_OK
        )

    def test_fluxo_calculos_parcelas_e_pagamentos(self):
        orcamento_id = self.criar_orcamento_com_item(desconto_tipo='PERCENTUAL', desconto_valor='10.00')
        orcamento = Orcamento.objects.get(pk=orcamento_id)
        self.assertEqual(orcamento.subtotal, Decimal('100.00'))
        self.assertEqual(orcamento.total, Decimal('90.00'))
        self.aprovar(orcamento_id)
        parcelas = self.client.post(
            f'/api/v1/orcamentos/{orcamento_id}/parcelar/',
            {'quantidade_parcelas': 3, 'primeiro_vencimento': str(date.today())},
            format='json',
        )
        self.assertEqual(parcelas.status_code, status.HTTP_201_CREATED)
        self.assertEqual([p['valor'] for p in parcelas.data], ['30.00', '30.00', '30.00'])
        parcial = self.client.post(
            '/api/v1/pagamentos/',
            {'orcamento': orcamento_id, 'parcela': parcelas.data[0]['id'], 'valor': '10.00', 'forma_pagamento': 'PIX'},
            format='json',
        )
        integral = self.client.post(
            '/api/v1/pagamentos/',
            {
                'orcamento': orcamento_id,
                'parcela': parcelas.data[0]['id'],
                'valor': '20.00',
                'forma_pagamento': 'DINHEIRO',
            },
            format='json',
        )
        final = self.client.post(
            '/api/v1/pagamentos/',
            {'orcamento': orcamento_id, 'valor': '60.00', 'forma_pagamento': 'TRANSFERENCIA'},
            format='json',
        )
        self.assertEqual(parcial.status_code, status.HTTP_201_CREATED)
        self.assertEqual(integral.status_code, status.HTTP_201_CREATED)
        self.assertEqual(final.status_code, status.HTTP_201_CREATED)
        orcamento.refresh_from_db()
        self.assertEqual(orcamento.valor_pago, Decimal('90.00'))
        self.assertEqual(orcamento.saldo, Decimal('0.00'))
        self.assertEqual(self.client.get(f'/api/v1/parcelas/{parcelas.data[0]["id"]}/').data['status'], 'PAGA')

    def test_desconto_valor_invalido_e_transicoes_protegidas(self):
        orcamento_id = self.criar_orcamento_com_item()
        desconto = self.client.patch(
            f'/api/v1/orcamentos/{orcamento_id}/', {'desconto_tipo': 'VALOR', 'desconto_valor': '101.00'}, format='json'
        )
        direto = self.client.patch(f'/api/v1/orcamentos/{orcamento_id}/', {'status': 'APROVADO'}, format='json')
        direto_acao = self.client.post(f'/api/v1/orcamentos/{orcamento_id}/aprovar/')
        self.assertEqual(desconto.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(direto.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(direto_acao.status_code, status.HTTP_400_BAD_REQUEST)

    def test_permissoes_e_isolamento(self):
        orcamento_id = self.criar_orcamento_com_item()
        self.client.force_authenticate(self.paciente)
        criacao = self.client.post(
            '/api/v1/orcamentos/', {'paciente': self.paciente.id, 'titulo': 'Tentativa'}, format='json'
        )
        item = self.client.post(
            '/api/v1/itens-orcamento/',
            {'orcamento': orcamento_id, 'descricao': 'Tentativa', 'quantidade': 1, 'valor_unitario': '1.00'},
            format='json',
        )
        pagamento = self.client.post(
            '/api/v1/pagamentos/', {'orcamento': orcamento_id, 'valor': '1.00', 'forma_pagamento': 'PIX'}, format='json'
        )
        self.assertEqual(criacao.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(item.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(pagamento.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(f'/api/v1/orcamentos/{orcamento_id}/').status_code, status.HTTP_200_OK)
        self.client.force_authenticate(self.dentista_b_usuario)
        self.assertEqual(self.client.get(f'/api/v1/orcamentos/{orcamento_id}/').status_code, status.HTTP_404_NOT_FOUND)
        outra_clinica = self.client.post(
            '/api/v1/orcamentos/', {'paciente': self.paciente.id, 'titulo': 'Invasao'}, format='json'
        )
        self.assertEqual(outra_clinica.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pagamento_nao_excede_saldo_e_referencia_e_unica(self):
        orcamento_id = self.criar_orcamento_com_item()
        excesso = self.client.post(
            '/api/v1/pagamentos/',
            {'orcamento': orcamento_id, 'valor': '101.00', 'forma_pagamento': 'PIX'},
            format='json',
        )
        primeiro = self.client.post(
            '/api/v1/pagamentos/',
            {'orcamento': orcamento_id, 'valor': '10.00', 'forma_pagamento': 'PIX', 'referencia_externa': 'pix-123'},
            format='json',
        )
        repetido = self.client.post(
            '/api/v1/pagamentos/',
            {'orcamento': orcamento_id, 'valor': '10.00', 'forma_pagamento': 'PIX', 'referencia_externa': 'pix-123'},
            format='json',
        )
        self.assertEqual(excesso.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(primeiro.status_code, status.HTTP_201_CREATED)
        self.assertEqual(repetido.status_code, status.HTTP_400_BAD_REQUEST)
