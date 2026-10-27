import csv
import io
import json
import re
import sys
import unicodedata

from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.functions import create_map, lit, col
from pyspark.sql.types import StringType, StructField, StructType
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions


# =========================
# 1) Glue job bootstrap
# =========================
args = getResolvedOptions(sys.argv, ["JOB_NAME", "input_path", "output_path"])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

# =========================
# 2) Caminhos dinâmicos
# =========================
INPUT_PATH = args["input_path"]
OUTPUT_PATH = args["output_path"].rstrip("/")


# =========================
# 3) Funções utilitárias
# =========================
def normalize_colname(c: str) -> str:
    c = str(c).strip().lower()
    c = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode("ascii")
    c = c.replace(" ", "_").replace(".", "")
    c = re.sub(r"[^a-z0-9_]", "_", c)
    c = re.sub(r"_+", "_", c).strip("_")
    if not c:
        c = "coluna"
    return c


def deduplicate_columns(cols):
    seen = {}
    out = []
    for c in cols:
        if c not in seen:
            seen[c] = 0
            out.append(c)
        else:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
    return out


# =========================
# 4) Leitura CSV
# =========================
def source_document(content):
    # Parse whole documents: the survey contains embedded newlines and doubled
    # quotes. JVM CSV parsing previously split or merged valid survey records.
    reader = csv.reader(
        io.StringIO(content.decode("iso-8859-1"), newline=""),
        delimiter=";", quotechar='"', doublequote=True,
    )
    header = next(reader)
    if header and header[0].lower().startswith("column"):
        header = next(reader)
    return tuple(deduplicate_columns([normalize_colname(c) for c in header])), reader


def source_width(content):
    header, reader = source_document(content)
    return max((len(row) for row in reader), default=len(header))


def source_rows(content, columns):
    header, reader = source_document(content)
    if header != tuple(columns[:len(header)]):
        raise ValueError("Cabecalhos diferentes entre arquivos de origem")
    for row in reader:
        if not row:
            continue
        # Preserve extra source fields and pad short records instead of shifting
        # named columns. Empty CSV fields retain SQL NULL semantics.
        if len(row) > len(columns):
            raise ValueError("Registro excede a largura calculada da origem")
        yield tuple(value if value != "" else None for value in row) + (None,) * (len(columns) - len(row))


# A multiline document cannot be split at arbitrary line boundaries. Distribute
# independent files to Spark workers and keep only headers/widths on the driver.
documents = sc.binaryFiles(INPUT_PATH).cache()
headers = documents.map(lambda item: source_document(item[1])[0]).distinct().collect()
if len(headers) != 1:
    raise ValueError("Informe arquivos CSV com um unico esquema de origem")
columns = list(headers[0])
width = documents.map(lambda item: source_width(item[1])).max()
columns += [f"coluna_extra_{index}" for index in range(len(columns), width)]
schema = StructType([StructField(name, StringType(), True) for name in columns])
df = spark.createDataFrame(documents.flatMap(lambda item: source_rows(item[1], columns)), schema)


# =========================
# 5) Removendo colunas
# =========================
colunas_rem = [
    "Idade", "Genero", "uf_onde_mora", "Cor/raca/etnia", "Pcd",
    "Experiencia profissional prejudicada", "Aspectos prejudicados", "Mudou de estado?",
    "Qual o principal motivo da sua insatisfação com a empresa atual?",
    "Falta de oportunidade de crescimento no emprego atual",
    "Salário atual não corresponde ao mercado",
    "Não tenho uma boa relação com meu líder/gestor",
    "Gostaria de trabalhar em em outra área de atuação",
    "Gostaria de receber mais benefícios",
    "O clima de trabalho/ambiente não é bom",
    "Falta de maturidade analítica na empresa",
    "Você participou de entrevistas de emprego nos últimos 6 meses?",
    "Você pretende mudar de emprego nos próximos 6 meses?",
    "Quais os principais critérios que você leva em consideração no momento de decidir onde trabalhar?",
    "Benefícios", "Propósito do trabalho e da empresa", "Flexibilidade de trabalho remoto",
    "Ambiente e clima de trabalho",
    "Oportunidade de aprendizado e trabalhar com referências na área",
    "Plano de carreira e oportunidades de crescimento profissional",
    "Maturidade da empresa em termos de tecnologia e dados",
    "Qualidade dos gestores e líderes", "Reputação que a empresa tem no mercado",
    "Qual a forma de trabalho ideal para você?",
    "Caso sua empresa decida pelo modelo 100% presencial qual será sua atitude?",
    "Sua empresa passu por layoff em 2022?",
    "Qual o número aproximado de pessoas que atuam com dados na sua empresa hoje?",
    "Quais desses papéis/cargos fazem parte do time (ou chapter) de dados da sua empresa?",
    "Quais dessas responsabilidades fazem parte da sua rotina atual de trabalho como gestor?",
    "Pensar na visão de longo prazo de dados da empresa e fortalecimento da cultura analítica da companhia.",
    "Organização de treinamentos e iniciativas com o objetivo de aumentar a maturidade analítica das áreas de negócios.",
    "Atração",
    "Decisão sobre contratação de ferramentas e tecnologias relacionadas a dados.",
    "Sou gestor da equipe responsável pela engenharia de dados e por manter o data lake da empresa como fonte única dos dados",
    "Sou gestor da equipe responsável pela entrega de dados",
    "Sou gestor da equipe responsável por iniciativas e projetos envolvendo inteligência artificial e machine learning.",
    "Apesar de ser gestor ainda atuo na parte técnica",
    "Gestão de projetos de dados", "Gestão de produtos de dados", "Gestão de pessoas",
    "Quais são os 3 maiores desafios que você tem como gestor no atual momento?",
    "Contratar novos talentos.", "Reter talentos.",
    "Convencer a empresa a aumentar os investimentos na área de dados.",
    "Gestão de equipes no ambiente remoto.",
    "Gestão de projetos envolvendo áreas multidisciplinares da empresa.",
    "Organizar as informações e garantir a qualidade e confiabilidade.",
    "Conseguir processar e armazenar um alto volume de dados.",
    "Conseguir gerar valor para as áreas de negócios através de estudos e experimentos.",
    "Desenvolver e manter modelos machine learning em produção.",
    "Gerenciar a expectativa das áreas de negócio em relação as entregas das equipes de dados.",
    "Garantir a manutenção dos projetos e modelos em produção",
    "Conseguir levar inovação para a empresa através dos dados.",
    "Garantir retorno do investimento (roi) em projetos de dados.",
    "Dividir o tempo entre entregas técnicas e gestão.",
    "Mesmo que esse não seja seu cargo formal",
    "Qual seu objetivo na área de dados?",
    "Qual oportunidade você está buscando?",
    "Há quanto tempo você busca uma oportunidade na área de dados?",
    "Como tem sido a busca por um emprego na área de dados?"
]

colunas_rem_norm = [normalize_colname(c) for c in colunas_rem]
cols_existentes_para_remover = [c for c in colunas_rem_norm if c in df.columns]
df_final = df.drop(*cols_existentes_para_remover)

# Keep numeric indicators typed in Parquet; Athena compares these values to 1.
# Reject unexpected source values instead of silently converting them to null.
language_columns = [
    "sql", "r", "python", "c_c_c", "net", "java", "julia", "sas_stata",
    "visual_basic_vba", "scala", "matlab", "php", "javascript",
    "nao_utilizo_nenhuma_linguagem",
]
missing_columns = set(language_columns + ["id", "nivel", "atuacao"]) - set(df_final.columns)
if missing_columns:
    raise ValueError(f"Colunas obrigatorias ausentes: {sorted(missing_columns)}")
invalid_language = F.lit(False)
for name in language_columns:
    value = F.trim(F.col(name))
    invalid_language = invalid_language | (
        value.isNotNull() & (value != "") & ~value.isin("0", "1", "0.0", "1.0")
    )
if df_final.filter(invalid_language).limit(1).count():
    raise ValueError("Indicador de linguagem fora do dominio 0/1 na fonte")
for name in language_columns:
    df_final = df_final.withColumn(name, F.col(name).cast("int"))


# =========================
# 6) Contagem de nulos
# =========================
null_counts = df_final.select([
    F.count(F.when(F.col(c).isNull() | (F.trim(F.col(c)) == ""), c)).alias(c)
    for c in df_final.columns
])

result = null_counts.collect()[0].asDict()
print("Nulos por coluna:")
print(json.dumps(result, indent=2, ensure_ascii=False))


# =========================
# 7) Dataframe de informações gerais
# =========================
cargos_cols = [
    "analytics_engineer",
    "engenharia_de_dados_data_engineer",
    "analista_de_dados_data_analyst",
    "cientista_de_dados_data_scientist",
    "database_administrator_dba",
    "analista_de_business_intelligence_bi",
    "arquiteto_de_dados_data_architect",
    "data_product_manager_dpm",
    "business_analyst"
]

if all(c in df_final.columns for c in cargos_cols):
    cargos = df_final.withColumn(
        "cargo_map",
        create_map(
            lit("analytics_engineer"), col("analytics_engineer"),
            lit("engenharia_de_dados/data_engineer"), col("engenharia_de_dados_data_engineer"),
            lit("analista_de_dados/data_analyst"), col("analista_de_dados_data_analyst"),
            lit("cientista_de_dados/data_scientist"), col("cientista_de_dados_data_scientist"),
            lit("database_administrator/dba"), col("database_administrator_dba"),
            lit("analista_de_business_intelligence/bi"), col("analista_de_business_intelligence_bi"),
            lit("arquiteto_de_dados/data_architect"), col("arquiteto_de_dados_data_architect"),
            lit("data_product_manager/dpm"), col("data_product_manager_dpm"),
            lit("business_analyst"), col("business_analyst")
        )
    )
else:
    cargos = df_final

cols_infos = [
    "id", "faixa_idade", "vive_no_brasil", "estado_onde_mora",
    "regiao_onde_mora", "nivel_de_ensino", "area_de_formacao",
    "cargo_atual", "nivel", "faixa_salarial"
]

cols_infos_existentes = [c for c in cols_infos if c in df_final.columns]
df_infos = df_final.select(*cols_infos_existentes)

if "id" in df_infos.columns and "id" in cargos.columns and "cargo_map" in cargos.columns:
    df_gerais = df_infos.join(cargos.select("id", "cargo_map"), on="id", how="left")
    # CSV only supports scalar columns. Keep the auxiliary map as JSON text.
    df_gerais = df_gerais.withColumn("cargo_map", F.to_json(F.col("cargo_map")))
else:
    df_gerais = df_infos


# =========================
# 8) Escrita no S3
# =========================
print(f"Registros Silver: {df_final.count()}")
# The crawler targets /silver/: keep one schema there so it creates table silver.
# Parquet preserves column boundaries, numeric types and nulls in survey answers.
# Auxiliary information has a different schema and lives outside that prefix.
GENERAL_OUTPUT_PATH = f"{OUTPUT_PATH}_gerais"
(
    df_final.write.mode("overwrite").parquet(OUTPUT_PATH)
)

(
    df_gerais.write.mode("overwrite")
    .option("header", "true")
    .option("sep", ",")
    .csv(GENERAL_OUTPUT_PATH)
)

print(f"Silver Parquet salva em: {OUTPUT_PATH}; CSV auxiliar em: {GENERAL_OUTPUT_PATH}")

job.commit()
