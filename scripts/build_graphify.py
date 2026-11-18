import json
from pathlib import Path
from graphify.extract import collect_files, extract
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json, to_html


root = Path("d:/Jarvis")
detect = json.loads(Path("graphify-out/.graphify_detect.json").read_text(encoding="utf-8"))
code_files = [Path(f) for f in detect.get("files", {}).get("code", [])]
print(f"1. Extracting AST for {len(code_files)} code files...")

ast_res = extract(code_files, cache_root=root)
Path("graphify-out/.graphify_ast.json").write_text(json.dumps(ast_res, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"AST done: {len(ast_res['nodes'])} nodes, {len(ast_res['edges'])} edges")

extraction = {
    'nodes': ast_res['nodes'],
    'edges': ast_res['edges'],
    'hyperedges': [],
    'input_tokens': 0,
    'output_tokens': 0
}
Path("graphify-out/.graphify_extract.json").write_text(json.dumps(extraction, indent=2, ensure_ascii=False), encoding="utf-8")

# Build Graph
print("2. Building graph from extraction...")
G = build_from_json(extraction, root=str(root), directed=False)
print(f"Graph nodes: {G.number_of_nodes()}, edges: {G.number_of_edges()}")

# Cluster & Analyze
print("3. Clustering and analyzing community graph...")
communities = cluster(G)
cohesion = score_all(G, communities)
tokens = {'input': 0, 'output': 0}
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
labels = {cid: f'Community {cid}' for cid in communities}
questions = suggest_questions(G, communities, labels)

# Export
print("4. Exporting graph.json, GRAPH_REPORT.md, and graph.html...")
to_json(G, communities, 'graphify-out/graph.json')
report = generate(G, communities, cohesion, labels, gods, surprises, detect, tokens, str(root), suggested_questions=questions)
Path('graphify-out/GRAPH_REPORT.md').write_text(report, encoding="utf-8")
Path('graphify-out/.graphify_labels.json').write_text(json.dumps(labels), encoding="utf-8")

try:
    to_html(G, communities, 'graphify-out/graph.html', community_labels=labels)
except Exception as e:
    print(f"HTML export notice: {e}")


print("✅ Graphify Knowledge Graph Built Successfully in graphify-out/!")
