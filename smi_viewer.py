from flask import Flask, render_template, jsonify
import subprocess
import json
import os
from collections import deque
from datetime import datetime
import traceback

app = Flask(__name__)

PROTECTED_PROCESSES = [
    'Xorg',
    'gnome-shell',
    'kde-plasma',
    'sddm',
    'lightdm'
]

# Dictionnaire global pour l'historique
history = {}

def get_gpu_info():
    try:
        print("Tentative d'exécution de nvidia-smi...")
        result = subprocess.check_output([
            'nvidia-smi', 
            '--query-gpu=index,gpu_name,temperature.gpu,memory.used,memory.total,utilization.gpu,power.draw',
            '--format=csv,noheader,nounits'
        ], stderr=subprocess.PIPE).decode()
        
        print("Résultat brut:", result)
        
        gpus = []
        processes = []
        
        # Parser les données de chaque GPU
        for line in result.strip().split('\n'):
            try:
                gpu_data = [x.strip() for x in line.split(',')]
                print("GPU data après split:", gpu_data)
                
                gpu_id = str(gpu_data[0])  # Assurer que l'ID est une chaîne
                
                gpu = {
                    'id': gpu_id,
                    'name': gpu_data[1],
                    'temperature': gpu_data[2],
                    'memory_used': gpu_data[3],
                    'memory_total': gpu_data[4],
                    'utilization': gpu_data[5],
                    'power': gpu_data[6]
                }
                
                # Initialiser l'historique pour ce GPU si nécessaire
                if gpu_id not in history:
                    history[gpu_id] = {
                        'timestamps': deque(maxlen=30),
                        'temperature': deque(maxlen=30),
                        'utilization': deque(maxlen=30),
                        'memory': deque(maxlen=30),
                        'power': deque(maxlen=30)
                    }
                
                # Mettre à jour l'historique
                now = datetime.now().strftime('%H:%M:%S')
                history[gpu_id]['timestamps'].append(now)
                history[gpu_id]['temperature'].append(float(gpu['temperature']))
                history[gpu_id]['utilization'].append(float(gpu['utilization']))
                history[gpu_id]['memory'].append(float(gpu['memory_used']))
                history[gpu_id]['power'].append(float(gpu['power']))
                
                gpus.append(gpu)
            except Exception as e:
                print(f"Erreur parsing ligne GPU: {str(e)}")
                continue
        
        # Récupérer les processus
        process_result = subprocess.check_output(['nvidia-smi'], stderr=subprocess.PIPE).decode()
        print("Résultat processus brut:", process_result)  # Debug
        process_section = False
        
        for line in process_result.split('\n'):
            if '| Processes:' in line:
                process_section = True
                continue
                
            if process_section and '|' in line:
                if 'GPU   GI   CI' in line or '===' in line:
                    continue
                
                try:
                    parts = line.split('|')
                    if len(parts) >= 2:
                        info_part = parts[1].strip()
                        if not info_part:
                            continue
                        
                        info = info_part.split()
                        if len(info) >= 6:
                            gpu_id = info[0]
                            pid = info[3]
                            memory = info[-1].replace('MiB', '')
                            name = ' '.join(info[5:-1])
                            
                            if pid.isdigit():
                                process = {
                                    'gpu_id': gpu_id,
                                    'pid': int(pid),
                                    'memory': float(memory),
                                    'name': name
                                }
                                processes.append(process)
                except Exception as e:
                    print(f"Erreur parsing processus: {str(e)}")
                    continue

        print("GPUs détectés:", gpus)
        print("Processus détectés:", processes)
        
        # Préparer l'historique pour la réponse
        history_data = {}
        for gpu_id in history.keys():
            try:
                history_data[gpu_id] = {
                    'timestamps': list(history[gpu_id]['timestamps']),
                    'temperature': list(history[gpu_id]['temperature']),
                    'utilization': list(history[gpu_id]['utilization']),
                    'memory': list(history[gpu_id]['memory']),
                    'power': list(history[gpu_id]['power'])
                }
            except Exception as e:
                print(f"Erreur lors de la conversion de l'historique pour GPU {gpu_id}: {str(e)}")

        return {
            'gpus': gpus,
            'processes': processes,
            'history': history_data
        }

    except Exception as e:
        print(f"Erreur inattendue: {str(e)}")
        print("Traceback complet:", traceback.format_exc())
        return {'gpus': [], 'processes': [], 'history': {}}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/gpu_info')
def gpu_info():
    data = get_gpu_info()
    print("Données envoyées au frontend:", data)  # Pour voir ce qui est envoyé
    return jsonify(data)

@app.route('/kill/<int:pid>')
def kill_process(pid):
    try:
        os.kill(pid, 9)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/kill_all_gpu/<int:gpu_id>')
def kill_all_gpu_processes(gpu_id):
    try:
        data = get_gpu_info()
        killed_processes = []
        errors = []
        
        for process in data['processes']:
            # Vérifier si le processus est protégé
            if any(protected in process['name'] for protected in PROTECTED_PROCESSES):
                errors.append(f"Processus protégé ignoré: {process['name']} (PID: {process['pid']})")
                continue
                
            try:
                print(f"Tentative de kill du processus GPU: {process['pid']}")
                os.kill(process['pid'], 9)
                killed_processes.append(process['pid'])
            except Exception as e:
                errors.append(f"Erreur pour PID {process['pid']}: {str(e)}")
        
        if not killed_processes and not errors:
            return jsonify({
                'success': True,
                'message': 'Aucun processus GPU à terminer',
                'killed_processes': [],
                'errors': []
            })
            
        return jsonify({
            'success': True,
            'killed_processes': killed_processes,
            'errors': errors
        })
    except Exception as e:
        print(f"Erreur générale: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

if __name__ == '__main__':
    # Créer le dossier templates s'il n'existe pas
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True)
