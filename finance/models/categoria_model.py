"""
Modelo de Categoria Personalizada.

Localização: finance/models/categoria_model.py

Schema no MongoDB:
{
  _id: ObjectId,
  user_id: ObjectId,        # ID do usuário
  nome: String,             # Nome da categoria
  tipo: String,             # Tipo: 'receita', 'gasto', 'transporte', etc.
  descricao: String,        # Descrição (opcional)
  created_at: ISODate,
  updated_at: ISODate
}
"""
from typing import Dict, Any
from datetime import datetime
from bson import ObjectId


class CategoriaModel:
    """
    Modelo de dados para categorias personalizadas.
    """
    
    # Tipos de categorias disponíveis
    TIPOS = [
        ('receita', 'Receita'),
        ('entrada', 'Outras Entradas'),
        ('investimento', 'Investimentos'),
        ('alimentacao', 'Alimentação'),
        ('transporte', 'Transporte'),
        ('saude', 'Saúde e Bem Estar'),
        ('lazer', 'Lazer'),
        ('educacao', 'Educação'),
        ('habitacao', 'Habitação'),
        ('outros', 'Demais Despesas'),
    ]
    
    @staticmethod
    def create_categoria_data(user_id: str, nome: str, tipo: str,
                             descricao: str = '') -> Dict[str, Any]:
        """
        Cria estrutura de dados de categoria.
        
        Args:
            user_id: ID do usuário
            nome: Nome da categoria
            tipo: Tipo da categoria
            descricao: Descrição (opcional)
        
        Returns:
            Dict com dados da categoria
        """
        return {
            'user_id': ObjectId(user_id) if isinstance(user_id, str) else user_id,
            'nome': nome.strip(),
            'tipo': tipo.strip(),
            'descricao': descricao.strip() if descricao else '',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
    
    @staticmethod
    def get_categorias_predefinidas() -> Dict[str, list]:
        """
        Retorna categorias pré-definidas organizadas por tipo.
        
        Returns:
            Dict com categorias por tipo
        """
        return {
            'receita': [
                'Salário',
                'Aluguel Recebido',
                'Pensão',
                'Freelancer',
                'Distribuição Resultados',
                'Outras Receitas'
            ],
            'entrada': [
                'Transferência de contas',
                'Reembolsos e Adiantamentos',
                'Variação Cambial'
            ],
            'investimento': [
                'Aportes',
                'Resgates'
            ],
            'alimentacao': [
                'Supermercado',
                'Almoços fora de casa',
                'Delivery',
                'Outros Alimentação'
            ],
            'transporte': [
                'Prestação carro',
                'Seguro do carro',
                'IPVA',
                'Combustível',
                'Estacionamentos',
                'Lavagem',
                'Manutenção',
                'Transporte público',
                'Táxi/Uber',
                'Pedágios',
                'Multas',
                'Outros Transportes'
            ],
            'saude': [
                'Médicos, dentistas',
                'Farmácia',
                'Medicamentos',
                'Atividades físicas',
                'Estética',
                'Outros Saúde e Bem Estar'
            ],
            'lazer': [
                'Festas',
                'Jantares',
                'Cinema',
                'Mensalidade de clubes',
                'Viagens',
                'Futebol',
                'Outros Lazer'
            ],
            'educacao': [
                'Colégio',
                'Faculdade',
                'Livros',
                'Cursos',
                'Apps e Gadgets'
            ],
            'habitacao': [
                'Condomínio',
                'Aluguel',
                'Prestação da casa',
                'IPTU',
                'Água',
                'Luz',
                'Telefone',
                'TV',
                'Gás',
                'Empregados domésticos',
                'Manutenções',
                'Outros'
            ],
            'outros': [
                'Compras Diversas',
                'Roupas',
                'Seguro de Vida',
                'Telefone',
                'Presentes',
                'Tarifas bancárias',
                'Doações',
                'Ajuda familiar',
                'Imprevistos',
                'Taxas',
                'Impostos',
                'Outros'
            ]
        }
