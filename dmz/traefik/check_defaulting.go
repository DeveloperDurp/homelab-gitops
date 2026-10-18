// CEL test runner; build in a scratch Go module with cel-go v0.26.1.
// Invoke through check_access.py --admission-check /path/to/compiled-runner.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"strconv"
	"strings"

	"github.com/google/cel-go/cel"
	"github.com/google/cel-go/ext"
	"google.golang.org/protobuf/types/known/structpb"
)

type JSONPatch struct {
	Op   string `cel:"op" json:"op"`
	Path string `cel:"path" json:"path"`
	// This policy only patches middleware arrays; Kubernetes JSONPatch.value is dynamic.
	Value []map[string]string `cel:"value" json:"value"`
}

type Case struct {
	Name     string         `json:"name"`
	Object   map[string]any `json:"object"`
	Expected map[string]any `json:"expected"`
	Allowed  bool           `json:"allowed"`
}

func main() {
	var input struct {
		Mutation   string `json:"mutation"`
		Validation string `json:"validation"`
		Cases      []Case `json:"cases"`
	}
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		panic(err)
	}
	env, err := cel.NewEnv(cel.Variable("object", cel.DynType), cel.Container("main"),
		ext.TwoVarComprehensions(), ext.NativeTypes(reflect.TypeOf(JSONPatch{}), ext.ParseStructTags(true)))
	if err != nil {
		panic(err)
	}
	compile := func(expr string) cel.Program {
		ast, issues := env.Compile(expr)
		if issues.Err() != nil {
			panic(issues.Err())
		}
		p, err := env.Program(ast)
		if err != nil {
			panic(err)
		}
		return p
	}
	// Normalize native JSONPatch constructors to JSON to exercise the exact expression.
	mutation := compile("(" + input.Mutation + ").map(p, {'op': p.op, 'path': p.path, 'value': p.value})")
	validation := compile(input.Validation)
	patches := func(object any) []JSONPatch {
		out, _, err := mutation.Eval(map[string]any{"object": object})
		if err != nil {
			panic(err)
		}
		value, err := out.ConvertToNative(reflect.TypeOf(&structpb.Value{}))
		if err != nil {
			panic(err)
		}
		data, err := value.(*structpb.Value).MarshalJSON()
		if err != nil {
			panic(err)
		}
		var result []JSONPatch
		if err := json.Unmarshal(data, &result); err != nil {
			panic(err)
		}
		return result
	}
	for _, c := range input.Cases {
		for _, patch := range patches(c.Object) {
			pieces := strings.Split(patch.Path, "/")
			if patch.Op != "add" || len(pieces) != 5 || pieces[1] != "spec" || pieces[2] != "routes" || pieces[4] != "middlewares" {
				panic(patch)
			}
			index, err := strconv.Atoi(pieces[3])
			if err != nil {
				panic(err)
			}
			routes := c.Object["spec"].(map[string]any)["routes"].([]any)
			routes[index].(map[string]any)["middlewares"] = patch.Value
		}
		// Compare JSON values rather than Go slice representations after patching.
		encoded, err := json.Marshal(c.Object)
		if err != nil {
			panic(err)
		}
		if err := json.Unmarshal(encoded, &c.Object); err != nil {
			panic(err)
		}
		if !reflect.DeepEqual(c.Object, c.Expected) {
			panic(fmt.Sprintf("%s: unexpected mutation: %#v", c.Name, c.Object))
		}
		if len(patches(c.Object)) != 0 {
			panic(c.Name + ": mutation not idempotent")
		}
		out, _, err := validation.Eval(map[string]any{"object": c.Object})
		if err != nil {
			panic(err)
		}
		if out.Value() != c.Allowed {
			panic(fmt.Sprintf("%s: validation got %v expected %v", c.Name, out.Value(), c.Allowed))
		}
		fmt.Println("PASS", c.Name)
	}
	fmt.Printf("PASS: exact mutation CEL compiled, %d mutation + validation + idempotence cases\n", len(input.Cases))
}
