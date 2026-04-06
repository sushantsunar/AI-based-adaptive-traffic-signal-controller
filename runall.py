# runall.py
import threading
from main import main_loop  # your main traffic loop
from dashboard.app import app
import sys

# A flag to signal stopping the program
stop_flag = threading.Event()

# Modified main loop to check the stop_flag
def main_loop_with_stop():
    try:
        main_loop(stop_flag)  # pass the stop_flag to your main_loop
    except KeyboardInterrupt:
        print("\nSimulation stopped by user.")

# Thread to run Flask dashboard
def run_flask():
    app.run(debug=False, port=5000, use_reloader=False)

# Thread to listen for 'Q' input
def listen_for_quit():
    while True:
        user_input = input("Type q to quit: ").strip().upper()
        if user_input == "q":
            print("Stopping program...")
            stop_flag.set()  # set the flag
            break

# Start Flask server in a separate thread
threading.Thread(target=run_flask, daemon=True).start()

# Start listener thread for Q
threading.Thread(target=listen_for_quit, daemon=True).start()

# Run the main algorithm loop (blocking)
main_loop_with_stop()

print("Program exited gracefully.")
sys.exit()
