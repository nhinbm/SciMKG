# -*- coding: utf-8 -*-
import argparse
import json
import os
import glob
import time
from typing import Tuple
import re
allEntity = set()
finalEntity = set()

def process_directory(directory_path: str, models: list, subject: str, k: int,
                      use_conceptnet: bool = False, use_wikipedia: bool = False) -> None:
    # Keep each directory's augmentation scoped to its own concepts.
    allEntity.clear()
    finalEntity.clear()
    # obtain all txt
    txt_files = glob.glob(os.path.join(directory_path, '**', '*.txt'), recursive=True)
    for txt_file in txt_files:
        ner_file_path = txt_file.replace('.txt', '_Extractionner')
        # skip processed txt
        if os.path.exists(ner_file_path):
            integration_path = txt_file.replace('.txt', '_Intergrationner')
            if not os.path.exists(integration_path):
                raise ValueError(f"Incomplete EVI output for {txt_file}: missing {integration_path}")
            with open(integration_path, encoding='utf-8') as integration_file:
                lines = integration_file.read().splitlines()
            for offset in range(0, len(lines), 3):
                if offset + 1 >= len(lines):
                    raise ValueError(f"Incomplete Integration block in {integration_path}")
                concepts = lines[offset + 1].split()
                allEntity.update(concepts)
                finalEntity.update(concepts)
            continue
        # extract concepts
 
        candidate = extractConcepts(txt_file, models, subject,allEntity,k) 
        
    if use_conceptnet or use_wikipedia:
        results = expandExplanations(subject, use_conceptnet=use_conceptnet,
                                     use_wikipedia=use_wikipedia)
        output_path = os.path.join(directory_path, '_Augmentation.json')
        with open(output_path, 'w', encoding='utf-8') as output_file:
            json.dump({
                'resources': {'conceptnet': use_conceptnet, 'wikipedia': use_wikipedia},
                'explanations': results,
            }, output_file, ensure_ascii=False, indent=2)
                  
def extractConcepts(filePtah: str,models: list, subject: str, allEntity: set, k=3) -> list:

    
    """candidate format
    results.append([timestamp,candidate_set,sc_score,prompt])
    timestamp1, entities_set1, sc_score, prompt, max
    timestamp2, entities_set2, sc_score, prompt, max
    timestamp3, entities_set3, sc_score, prompt, max
    ...
    """

    # Extraction
    candidate = Extraction(filePtah, models, subject, allEntity, k)

    # Validation models  default k=5
    candidate = Validation(candidate, models, subject, k,filePtah)
    # Intergration
    candidate = Intergration(candidate,k,filePtah,model_count=len(models))

    return candidate
            
def Extraction(filePtah: str, models: str, subject: str, allEntity: set, k: int) -> Tuple[dict, set]:
    ner_file_path = filePtah.replace('.txt', '_Extractionner')
    with open(filePtah, 'r', encoding='utf-8') as file:
            print("*************************************")
            print(filePtah)
            print("*************************************")
            # save all entity in all time
            entity_set = set()
            # save entity and time in special time 
            entity_time_set = dict()
            prompt = f"""
            $
            Silently analyze the text to:
            a) Identify all nouns/noun phrases using syntactic tagging
            b) Filter these to retain only concepts related to {subject}
            c) STRICTLY OUTPUT ONLY the final {subject} concepts: In Simplified Chinese 
            As a single list using this exact format: -xxx\n-xxx\n-xxx
            No headers/explanations/other text
            Never reveal non-subject nouns or intermediate analysis.
            $
            """
            for line in file:
                try: 
                    timestamp, content = line.strip('"').split('": "', 1)
                    entity = ner("deepseek-v3", content + prompt)
                    entity =  re.findall(r"-\s*(\w+)", entity)
                    # save entity in this time  
                    entity_time = set()
                    # for
                    for item in entity:
                        if item not in allEntity:
                            allEntity.add(item)
                            entity_time.add(item)
                            entity_set.add(item)
                    entity_time_set[timestamp] = entity_time         
                except:
                    continue
                print("=====================================")  
                print(f"timestamp: {timestamp} Entities: {entity_set} model: deepseek-v3 ")
                print("=====================================")         

    
    results = []
    for timestamp, candidate_set in entity_time_set.items():
        sc_score = [1]*len(candidate_set)
        max = [0]*len(candidate_set)
        prompt = "hello,"
        results.append([timestamp,candidate_set,sc_score,prompt,max])
    print(results)
        
        
    # TODO write the results to file
    if not os.path.exists(ner_file_path):
        with open(ner_file_path, 'w', encoding='utf-8') as ner_file:
            for item in results:
                ner_file.write(f"{item[0]}")
                ner_file.write('\n')
                for entity in item[1]:
                    ner_file.write(f"{entity} ")
                ner_file.write('\n')
                for score in item[2]:
                    ner_file.write(f"{score} ")
                ner_file.write('\n')
                ner_file.write(f"{prompt}")
                ner_file.write('\n')
                for max in item[4]:
                    ner_file.write(f"{max} ")
                ner_file.write('\n')
                ner_file.write('\n')
                
                
        ner_file.close()
        
            
    else:
        with open(ner_file_path, 'a', encoding='utf-8') as ner_file:
            for item in results:
                ner_file.write(f"{item[0]}")
                ner_file.write('\n')
                for entity in item[1]:
                    ner_file.write(f"{entity} ")
                ner_file.write('\n')
                for score in item[2]:
                    ner_file.write(f"{score} ")
                ner_file.write('\n')
                ner_file.write(f"{prompt}")
                ner_file.write('\n')
                for max in item[4]:
                    ner_file.write(f"{max} ")
                ner_file.write('\n')
                ner_file.write('\n')
                
        ner_file.close()
    return results

def Validation(candidate: list, models: str, subject: str, k: int, filePtah: str) -> list:
    """candidate format
    results.append([timestamp,candidate_set,sc_score,prompt])
    timestamp1, entities_set1, sc_score, prompt, max
    timestamp2, entities_set2, sc_score, prompt, max
    timestamp3, entities_set3, sc_score, prompt, max
    ...
    """
    # k = iter
    # SELF-REFINE
    candidate = SELF_REFINE(candidate,subject,models,k,filePtah)
    return candidate

def SELF_REFINE(candidate: list, subject: str, models: str, k: int, filePtah:  str) -> str: 

    FEED_BACKE_internal_prompt = f"""
    $
    ---
    Analyze the extracted {subject} concepts to:
    a) NEVER modify or split original terms
    b) Identify terms with cross-disciplinary ambiguity (terms that hold distinct meanings in other academic fields)
    c) For each ambiguous term, provide a one-sentence clarification of its potential alternative academic meaning
    d) Format output EXACTLY as: "ambiguous term" ："reason"
    e) Output ONLY lines following this format without additional text
    f) Preserve original lexical structure
    
    Example analysis pattern:
    "系统" : "Could refer to computer systems in technology contexts"
    
    $
    """
    

    """candidate format
    results.append([timestamp,candidate_set,sc_score,prompt])
    timestamp1, entities_set1, sc_score, prompt, max
    timestamp2, entities_set2, sc_score, prompt, max
    timestamp3, entities_set3, sc_score, prompt, max
    ...
    """
    results = []

    for timestamp, entities_set, sc_score, prompt, max in candidate:
        if len(entities_set) == 0:
            continue
        candidate_list = list()
        for entity in entities_set:
            candidate_list.append(entity)
        for model in models: 
            sc_max = [0]*len(entities_set)
            prompt = "hello, "
            for i in range(0,k):
                
            # FEED_BACKE
                tmp = str(candidate_list)
                feedback = ner(model, tmp + FEED_BACKE_internal_prompt + prompt)
                
                # RE_FINE
                RE_FINE_internal_prompt = f"""
                $
                Concept Filtering Protocol for {subject}

                FEEDBACK ANALYSIS
                $
                {feedback}
                $
                (Note: Feedback analysis may contain errors.)
                (Each feedback item clearly indicates terms that are out-of-scope or ambiguous with respect to  {subject}. 
                
                CANDIDATE POOL
                "{candidate_list}"

                1.Perform primary pruning using the FEEDBACK ANALYSIS to remove terms that are not directly relevant to  {subject}.
                2.Secondary filtration: Apply  {subject} standards to ensure that all remaining terms are inherently  {subject} concepts rather than instruments, apparatuses, or tools merely utilized in {subject} experiments.  
                3. Eliminate redundancies and non-{subject} terms while preserving the original order.

                OUTPUT SPECIFICATIONS
                Strictly output in Markdown list format, with each term on a new line as follows:  
                - concept1  
                - concept2  
                - concept3  
                Maintain the original order of valid entries.  
                Output only the list, with no additional text.

                Filtered Result:  
                $
                    
                """
                print("*"*9)
                print(RE_FINE_internal_prompt)
                entity = ner(model,RE_FINE_internal_prompt)
                entity =  re.findall(r"-\s*(\w+)", entity)
                print(entity,model)
                print("*"*9)
                prompt = prompt + feedback + "\n"
                # SC_SCORE 
                entity = set(entity)
                for index , i in enumerate(entities_set):
                    if i in entity:
                        sc_score[index] += 1
                        sc_max[index] += 1

            for index, (i , j) in enumerate(zip(sc_max, max)) :
                if i > j:
                    max[index] = i
                else:
                    max[index] = j

        results.append([timestamp,entities_set,sc_score,prompt,max])
    for item in results:
        print(f"timestamp: {item[0]} Entities: {item[1]}")

    # TODO write the results to file
    ner_file_path = filePtah.replace('.txt', '_Validationner')
    if not os.path.exists(ner_file_path):
        with open(ner_file_path, 'w', encoding='utf-8') as ner_file:
            for item in results:
                ner_file.write(f"{item[0]}")
                ner_file.write('\n')
                for entity in item[1]:
                    ner_file.write(f"{entity} ")
                ner_file.write('\n')
                for score in item[2]:
                    ner_file.write(f"{score} ")
                ner_file.write('\n')
                ner_file.write(f"{item[3]}")
                for max in item[4]:
                    ner_file.write(f"{max} ")
                ner_file.write('\n')
                ner_file.write('\n')
                
        ner_file.close()
        
            
    else:
        with open(ner_file_path, 'a', encoding='utf-8') as ner_file:
            for item in results:
                ner_file.write(f"{item[0]}")
                ner_file.write('\n')
                for entity in item[1]:
                    ner_file.write(f"{entity} ")
                ner_file.write('\n')
                for score in item[2]:
                    ner_file.write(f"{score} ")
                ner_file.write('\n')
                ner_file.write(f"{item[3]}")
                for max in item[4]:
                    ner_file.write(f"{max} ")
                ner_file.write('\n')
                ner_file.write('\n')
        ner_file.close()         
    return results 

def Intergration(candidate: list, k: int, filePtah: str, model_count: int, alpha: float = 0.7)-> list:
    # SC_score
    """candidate format
    results.append([timestamp,candidate_set,sc_score,prompt])
    timestamp1, entities_set1, sc_score, prompt, max
    timestamp2, entities_set2, sc_score, prompt, max
    timestamp3, entities_set3, sc_score, prompt, max
    ...
    """
    if k <= 0 or model_count <= 0:
        raise ValueError("Integration requires positive iteration and model counts")
    if not 0 <= alpha <= 1:
        raise ValueError("alpha must be between 0 and 1")
    total_votes = model_count * k
    results = []
    for timestamp, entities_set, sc_score, prompt, max in candidate:
        if len(entities_set) != len(sc_score):
            raise ValueError("Each candidate concept must have one SC score")
        final_entity = set()
        for index, i in enumerate(entities_set):
            # Extraction initializes sc_score to 1; only validation votes count.
            # Equal-weight frequency is this fork's normalization choice.
            SC_ScoreG = (sc_score[index] - 1) / total_votes
            if not 0 <= SC_ScoreG <= 1:
                raise ValueError("SC score is outside the configured validation vote range")
    
            if SC_ScoreG >= alpha:
                final_entity.add(i)
        results.append([timestamp,final_entity])
        print(f"timestamp: {timestamp} Entities: {final_entity}")
    # TODO write the results to file
    ner_file_path = filePtah.replace('.txt', '_Intergrationner')
    if not os.path.exists(ner_file_path):
        with open(ner_file_path, 'w', encoding='utf-8') as ner_file:
            for item in results:
                ner_file.write(f"{item[0]}")
                ner_file.write('\n')
                for entity in item[1]:
                    ner_file.write(f"{entity} ")
                    finalEntity.add(entity)
                    
                ner_file.write('\n')
                ner_file.write('\n')
                
        ner_file.close()
    return results
      
def expandExplanations(subject: str, use_conceptnet: bool = False,
                       use_wikipedia: bool = False) -> list:
    if not (use_conceptnet or use_wikipedia):
        return []
    entity_explanation = []

    if use_conceptnet:
        conceptExpand(subject)
    if use_wikipedia:
        if __package__:
            from .Wikipediaapi_model import get_wikipedia_summary
        else:
            from Wikipediaapi_model import get_wikipedia_summary
    

    for item in sorted(finalEntity):
        summary = get_wikipedia_summary(item).get(item) if use_wikipedia else None
        if not summary or summary in ("not found", "error"):
            propmt = f"""
            $
            You will be provided with a {subject} discipline concept. Generate one concise Chinese sentence describing it, 
            strictly within 20 words. Use simple language, prioritize accuracy, and avoid technical jargon unless critical. 
            Output only the final sentence without explanations, punctuation, or markdown. The concept is 
            $  
            """      
            explanation = ner("deepseek-v3",propmt+str(item))
            entity_explanation.append([item,explanation])  
             
        else:
            propmt = f"""
            "Given a concept from the {subject} discipline, with its Wikipedia explanation provided as '{summary}',
            generate a concise one-sentence Chinese description (≤20 words) strictly based on the Wikipedia content. 
            Output only the generated description without explanations or markdown."
            """    
            explanation = ner("deepseek-v3",propmt+str(item))
            entity_explanation.append([item,explanation])  
            
  
  
    return entity_explanation

def conceptExpand(subject: str)-> list:
    if __package__:
        from .ConceptNet import get_surface_texts, extract_cell_nouns
    else:
        from ConceptNet import get_surface_texts, extract_cell_nouns

    prompt = f"""
    Silently analyze the text to:
                a) Filter these to keep ONLY K-12 pure {subject} concepts 
                b) STRICTLY OUTPUT ONLY the final pure {subject} concepts: In Simplified Chinese 
                As a single list using this exact format: -xxx\n-xxx\n-xxx
                No headers/explanations/other text
                Never reveal non-subject nouns or intermediate analysis.   
    """
    result = []
    
    for item in finalEntity:
        result_text,results_term = get_surface_texts(item)
        if result_text == None:
            continue
        related_nouns = extract_cell_nouns(result_text,results_term)
        if len(related_nouns) == 0:
            continue
        add_list = []
        for noun in sorted(related_nouns):
            print(f"- {noun.capitalize()}")
            add_list.append(noun.capitalize())
            
        add_list = str(add_list)
        entity = ner("deepseek-v3",add_list+prompt)
        entity =  re.findall(r"-\s*(\w+)", entity)
        for i in entity:
            if i not in allEntity and i not in finalEntity:
                result.append(i)
    for item in result:
        finalEntity.add(item)
    return result
    
def ner(model:str,content:str) -> str:
    import requests

    url = os.environ.get('SCIMKG_LLM_URL')
    api_key = os.environ.get('SCIMKG_LLM_API_KEY')
    if not url or not api_key:
        raise RuntimeError('Set SCIMKG_LLM_URL and SCIMKG_LLM_API_KEY before calling LLMs')
    payload = json.dumps({
    "model": model,
    "messages": [
        {
            "role": "user",
            "content": content
        }
    ]
    })
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    time.sleep(2)
    response = requests.request("POST", url, headers=headers, data=payload, timeout=60)
    response.raise_for_status()
    print("=============================================")
    print(content)
    print(response)
    print("=============================================")
    response_json = response.json()
    while True:
        try:
            return response_json["choices"][0]["message"]["content"]
        except:
            print(f"retry   {model}")
            time.sleep(70)
            a = ner(model,content)
            if a :
                return a
              
    
def main(filePathList: list, subject: str, models: list, k: int = 5,
         use_conceptnet: bool = False, use_wikipedia: bool = False) -> None:
    for path_to_your_directorys in filePathList:
        if not os.path.isdir(path_to_your_directorys):
            raise ValueError(f"Input directory does not exist: {path_to_your_directorys}")
        process_directory(path_to_your_directorys, models, subject, k=k,
                          use_conceptnet=use_conceptnet, use_wikipedia=use_wikipedia)

def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description='Run EVIA with optional external resources.')
    parser.add_argument('directories', nargs='+', help='Directories containing preprocessed lesson .txt files')
    parser.add_argument('--subject', required=True, help='Discipline to extract concepts for')
    parser.add_argument('--models', nargs='+', default=['gpt-4o', 'deepseek-v3', 'gemini-1.5-flash'])
    parser.add_argument('--iterations', type=int, default=5, help='Validation rounds per model (default: 5)')
    parser.add_argument('--use-conceptnet', action='store_true', help='Enable ConceptNet expansion (default: off)')
    parser.add_argument('--use-wikipedia', action='store_true', help='Enable Wikipedia retrieval for explanations (default: off)')
    args = parser.parse_args(argv)
    if args.iterations <= 0:
        parser.error('--iterations must be positive')
    return args
        
if __name__ == "__main__":

    args = parse_arguments()
    if not os.environ.get('SCIMKG_LLM_URL') or not os.environ.get('SCIMKG_LLM_API_KEY'):
        raise SystemExit('Set SCIMKG_LLM_URL and SCIMKG_LLM_API_KEY before running EVIA')
    main(args.directories, args.subject, args.models, k=args.iterations,
         use_conceptnet=args.use_conceptnet, use_wikipedia=args.use_wikipedia)
