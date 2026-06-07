import sys
import json

from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.functions import create_map, lit, col
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

INPUT_PATH = args["input_path"]
OUTPUT_PATH = args["output_path"].rstrip("/")


# =========================
# 2) Leitura da base silver
# =========================
df = (
    spark.read
    .option("header", "true")
    .option("sep", ",")
    .option("encoding", "utf-8")
    .option("quote", '"')
    .option("escape", '"')
    .csv(INPUT_PATH)
)

print(f"Linhas lidas da base silver: {df.count()}")
print(f"Colunas disponíveis: {len(df.columns)}")


# =========================
# 3) Funções utilitárias
# =========================
def pick_col(*names):
    for n in names:
        if n in df.columns:
            return col(n)
    return F.lit(None)


def map_to_text(map_col_name: str):
    """
    Converte uma coluna do tipo map em texto plano no formato:
    chave=valor|chave=valor|...
    Isso é mais seguro para CSV do que JSON.
    """
    return F.expr(
        f"concat_ws('|', transform(map_entries({map_col_name}), x -> concat(x.key, '=', coalesce(x.value, 'null'))))"
    )


# =========================
# 4) Colunas base do dataframe final
# =========================
cols_infos = [
    "id",
    "faixa_idade",
    "vive_no_brasil",
    "estado_onde_mora",
    "regiao_onde_mora",
    "nivel_de_ensino",
    "area_de_formacao",
    "cargo_atual",
    "nivel",
    "faixa_salarial",
    "regiao_de_origem",
    "numero_de_funcionarios",
    "gestor",
    "cargo_como_gestor",
    "atuacao",
    "remuneracao_salario",
    "atualmente_qual_a_sua_forma_de_trabalho"
]

cols_infos_existentes = [c for c in cols_infos if c in df.columns]
df_gold = df.select(*cols_infos_existentes)


# =========================
# 5) Cargo
# =========================
if "id" in df.columns:
    df_cargo = df.withColumn(
        "cargo",
        create_map(
            lit("analytics_engineer"), pick_col("analytics_engineer"),
            lit("engenharia_de_dados/data_engineer"), pick_col("engenharia_de_dados_data_engineer"),
            lit("analista_de_dados/data_analyst"), pick_col("analista_de_dados_data_analyst"),
            lit("cientista_de_dados/data_scientist"), pick_col("cientista_de_dados_data_scientist"),
            lit("database_administrator/dba"), pick_col("database_administrator_dba"),
            lit("analista_de_business_intelligence/bi"), pick_col("analista_de_business_intelligence_bi"),
            lit("arquiteto_de_dados/data_architect"), pick_col("arquiteto_de_dados_data_architect"),
            lit("data_product_manager/dpm"), pick_col("data_product_manager_dpm"),
            lit("business_analyst"), pick_col("business_analyst")
        )
    ).select("id", "cargo")
    df_gold = df_gold.join(df_cargo, on="id", how="left")


# =========================
# 6) Fontes de dados
# =========================
if "id" in df.columns:
    df_fontes = df.withColumn(
        "fonte_de_dados",
        create_map(
            lit("dados_relacionais_estruturados_em_bancos_sql"),
            pick_col("dados_relacionais_estruturados_em_bancos_sql_102", "dados_relacionais_estruturados_em_bancos_sql_93", "dados_relacionais_estruturados_em_bancos_sql"),
            lit("dados_armazenados_em_bancos_nosql"),
            pick_col("dados_armazenados_em_bancos_nosql103", "dados_armazenados_em_bancos_nosql94", "dados_armazenados_em_bancos_nosql"),
            lit("imagens"),
            pick_col("imagens104", "imagens95", "imagens"),
            lit("textos_documentos"),
            pick_col("textos_documentos105", "textos_documentos96", "textos_documentos"),
            lit("videos"),
            pick_col("videos106", "videos97", "videos"),
            lit("audios"),
            pick_col("audios107", "audios98", "audios"),
            lit("planilhas"),
            pick_col("planilhas108", "planilhas99", "planilhas"),
            lit("dados_georeferenciados"),
            pick_col("dados_georeferenciados109", "dados_georeferenciados100", "dados_georeferenciados")
        )
    ).select("id", "fonte_de_dados")
    df_gold = df_gold.join(df_fontes, on="id", how="left")


# =========================
# 7) Linguagens
# =========================
if "id" in df.columns:
    df_linguagens = df.withColumn(
        "linguagens",
        create_map(
            lit("sql"), pick_col("sql"),
            lit("r"), pick_col("r"),
            lit("python"), pick_col("python"),
            lit("c/c++/c#"), pick_col("c_c_c"),
            lit("net"), pick_col("net"),
            lit("java"), pick_col("java"),
            lit("julia"), pick_col("julia"),
            lit("sas/stata"), pick_col("sas_stata"),
            lit("visual_basic/vba"), pick_col("visual_basic_vba"),
            lit("scala"), pick_col("scala"),
            lit("matlab"), pick_col("matlab"),
            lit("php"), pick_col("php"),
            lit("javascript"), pick_col("javascript"),
            lit("nao_utilizo_nenhuma_linguagem"), pick_col("nao_utilizo_nenhuma_linguagem")
        )
    ).select("id", "linguagens")
    df_gold = df_gold.join(df_linguagens, on="id", how="left")


# =========================
# 8) Bancos de dados
# =========================
if "id" in df.columns:
    df_bd = df.withColumn(
        "database",
        create_map(
            lit("mysql"), pick_col("mysql"),
            lit("oracle"), pick_col("oracle"),
            lit("sql_server"), pick_col("sql_server"),
            lit("amazon_aurora_ou_rds"), pick_col("amazon_aurora_ou_rds"),
            lit("dynamodb"), pick_col("dynamodb"),
            lit("coachdb"), pick_col("coachdb"),
            lit("cassandra"), pick_col("cassandra"),
            lit("mongodb"), pick_col("mongodb"),
            lit("mariadb"), pick_col("mariadb"),
            lit("datomic"), pick_col("datomic"),
            lit("s3"), pick_col("s3"),
            lit("postgresql"), pick_col("postgresql"),
            lit("elasticsearch"), pick_col("elasticsearch"),
            lit("db2"), pick_col("db2"),
            lit("microsoft_access"), pick_col("microsoft_access"),
            lit("sqlite"), pick_col("sqlite"),
            lit("sybase"), pick_col("sybase"),
            lit("firebase"), pick_col("firebase"),
            lit("vertica"), pick_col("vertica"),
            lit("redis"), pick_col("redis"),
            lit("neo4j"), pick_col("neo4j"),
            lit("google_bigquery"), pick_col("google_bigquery"),
            lit("google_firestore"), pick_col("google_firestore"),
            lit("amazon_redshift"), pick_col("amazon_redshift"),
            lit("amazon_athena"), pick_col("amazon_athena"),
            lit("snowflake"), pick_col("snowflake"),
            lit("databricks"), pick_col("databricks"),
            lit("hbase"), pick_col("hbase"),
            lit("presto"), pick_col("presto"),
            lit("splunk"), pick_col("splunk"),
            lit("sap_hana"), pick_col("sap_hana"),
            lit("hive"), pick_col("hive"),
            lit("firebird"), pick_col("firebird")
        )
    ).select("id", "database")
    df_gold = df_gold.join(df_bd, on="id", how="left")


# =========================
# 9) Cloud / BI
# =========================
if "id" in df.columns:
    df_cloud = df.withColumn(
        "cloud",
        create_map(
            lit("azure_(microsoft)"), pick_col("azure_microsoft"),
            lit("amazon_web_services_(aws)"), pick_col("amazon_web_services_aws"),
            lit("google_cloud_(gcp)"), pick_col("google_cloud_gcp"),
            lit("microsoft_powerbi"), pick_col("microsoft_powerbi166", "microsoft_powerbi167"),
            lit("qlik_view/qlik_sense"), pick_col("qlik_view_qlik_sense"),
            lit("tableau"), pick_col("tableau"),
            lit("metabase"), pick_col("metabase"),
            lit("superset"), pick_col("superset"),
            lit("redash"), pick_col("redash"),
            lit("microstrategy"), pick_col("microstrategy"),
            lit("ibm_analytics/cognos"), pick_col("ibm_analytics_cognos"),
            lit("sap_business_objects"), pick_col("sap_business_objects"),
            lit("oracle_business_intelligence"), pick_col("oracle_business_intelligence"),
            lit("amazon_quicksight"), pick_col("amazon_quicksight"),
            lit("salesforce/einstein_analytics"), pick_col("salesforce_einstein_analytics"),
            lit("mode"), pick_col("mode"),
            lit("alteryx"), pick_col("alteryx180", "alteryx212", "alteryx272"),
            lit("birst"), pick_col("birst"),
            lit("looker"), pick_col("looker"),
            lit("google_data_studio"), pick_col("google_data_studio"),
            lit("sas_visual_analytics"), pick_col("sas_visual_analytics"),
            lit("grafana"), pick_col("grafana"),
            lit("tibco_spotfire"), pick_col("tibco_spotfire"),
            lit("pentaho"), pick_col("pentaho187", "pentaho211", "pentaho271")
        )
    ).select("id", "cloud")
    df_gold = df_gold.join(df_cloud, on="id", how="left")


# =========================
# 10) Converter maps para texto seguro para CSV
# =========================
for c in ["cargo", "fonte_de_dados", "linguagens", "database", "cloud"]:
    if c in df_gold.columns:
        df_gold = df_gold.withColumn(c, map_to_text(c))


# =========================
# 11) Escrita no S3
# =========================
(df_gold.write.mode("overwrite")
 .option("header", "true")
 .option("sep", ",")
 .option("quote", "\"")
 .option("escape", "\"")
 .csv(f"{OUTPUT_PATH}/df_gold"))

print(f"Gold salvo em: {OUTPUT_PATH}/df_gold")

job.commit()