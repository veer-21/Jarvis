import sys
import os
import inspect

sys.path.insert(0, r"d:\Home\H.W. OR Self\Jarvis")

from core.brain.brain import Brain
from core.brain.tool_router import ToolRouter

def main():
    brain = Brain()
    router = brain.tools
    
    inventory = []
    
    for name, schema in router._registry.items():
        func = schema.callable
        sig = inspect.signature(func)
        
        params = []
        for param_name, param in sig.parameters.items():
            ptype = param.annotation.__name__ if hasattr(param.annotation, "__name__") else str(param.annotation)
            if ptype == "_empty": ptype = "Any"
            params.append(f"{param_name}: {ptype}")
            
        ret_type = sig.return_annotation.__name__ if hasattr(sig.return_annotation, "__name__") else str(sig.return_annotation)
        if ret_type == "_empty": ret_type = "Any"
        
        inventory.append({
            "name": schema.name,
            "function": func.__name__,
            "category": schema.category,
            "risk_level": schema.risk_level.value,
            "parameters": params,
            "return_type": ret_type
        })
        
    with open(r"d:\Home\H.W. OR Self\Jarvis\inventory_output.txt", "w", encoding="utf-8") as f:
        for tool in sorted(inventory, key=lambda x: x["category"] + x["name"]):
            f.write(f"Tool: {tool['name']}\n")
            f.write(f"  Function:    {tool['function']}\n")
            f.write(f"  Category:    {tool['category']}\n")
            f.write(f"  Risk Level:  {tool['risk_level']}\n")
            f.write(f"  Parameters:  {', '.join(tool['parameters']) if tool['parameters'] else 'None'}\n")
            f.write(f"  Return Type: {tool['return_type']}\n\n")

if __name__ == "__main__":
    main()
