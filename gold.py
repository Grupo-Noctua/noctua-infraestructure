import sys
import re
import unicodedata
import json
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.sql import functions as F

args = getResolvedOptions(sys.argv, ["JOB_NAME", "input_path", "output_path"])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

INPUT_PATH = args["input_path"]
OUTPUT_PATH = args["output_path"].rstrip("/")

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

df = (
    spark.read
    .option("header", "true")
    .option("sep", ",")  # OU ";" conforme seu dado!
    .option("encoding", "utf-8")
    .csv(INPUT_PATH)
)


normalized = deduplicate_columns([normalize_colname(c) for c in df.columns])
df = df.toDF(*normalized)


# ESCREVE RESULTADO EM GOLD
(df.write.mode("overwrite")
   .option("header", "true")
   .option("sep", ",")
   .csv(f"{OUTPUT_PATH}/df_gold"))

print(f"Arquivo final salvo em: {OUTPUT_PATH}/df_gold")

job.commit()