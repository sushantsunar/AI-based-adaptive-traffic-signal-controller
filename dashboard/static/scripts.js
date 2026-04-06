setInterval(() => {
    fetch("/data")
    .then(res => res.json())
    .then(data => {

        document.getElementById("cycle").innerText = data.cycle;
        document.getElementById("time").innerText = data.remaining_time;

        ["N","S","E","W"].forEach(d => {
            let box = document.getElementById(d);
            box.className = "box";
            if (data.current_green === d)
                box.classList.add("green");
            else
                box.classList.add("red");
        });

        document.getElementById("priority").innerText =
            JSON.stringify(data.priority, null, 2);

        document.getElementById("emergency").innerText =
            JSON.stringify(data.emergency, null, 2);
    })
}, 1000);
