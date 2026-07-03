package com.tcd.app

import android.app.AlertDialog
import android.content.DialogInterface
import android.content.Intent
import android.net.Uri
import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.drawable.BitmapDrawable
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.gridlayout.widget.GridLayout
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.Socket
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.ConcurrentHashMap
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {
    private var socket: Socket? = null
    private var output: PrintWriter? = null
    private var input: BufferedReader? = null
    private var deviceId = ""
    
    private val buttonMap = ConcurrentHashMap<String, View>()
    private val buttonDataMap = ConcurrentHashMap<String, JSONObject>()
    private val imageCache = ConcurrentHashMap<String, Bitmap>()
    private val pendingImages = ConcurrentHashMap<String, MutableList<String>>() // filename -> list of IDs
    private val specialEmptyViews = ConcurrentHashMap<String, android.widget.ImageView>() // ID -> ImageView
    private var backgroundFilename: String? = null
    private var bgImageView: android.widget.ImageView? = null
    private var lastIp: String = ""
    private var buttonGrid: GridLayout? = null
    
    private var fullLayoutData: JSONObject? = null
    private var currentPageIndex: Int = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        setTitle("Tactical Command Deck v1.2")

        val prefs = getSharedPreferences("TCD_PREFS", MODE_PRIVATE)
        lastIp = prefs.getString("last_ip", "") ?: ""
        
        deviceId = prefs.getString("device_id", "") ?: ""
        if (deviceId.isEmpty()) {
            deviceId = "android_" + java.util.UUID.randomUUID().toString().substring(0, 8)
            prefs.edit().putString("device_id", deviceId).apply()
        }

        val ipInput = findViewById<EditText>(R.id.ipInput)
        val connectBtn = findViewById<Button>(R.id.connectBtn)
        val exitBtn = findViewById<Button>(R.id.exitBtn)
        val statusText = findViewById<TextView>(R.id.statusText)
        buttonGrid = findViewById<GridLayout>(R.id.buttonGrid)
        val pairingLayout = findViewById<LinearLayout>(R.id.pairingLayout)
        val pairingCodeInput = findViewById<EditText>(R.id.pairingCodeInput)
        val pairBtn = findViewById<Button>(R.id.pairBtn)
        bgImageView = findViewById(R.id.backgroundImage)

        exitBtn.setOnClickListener {
            finishAffinity()
        }

        val pageDropdownText = findViewById<TextView>(R.id.pageDropdownText)
        var lastMenuOpenTime: Long = 0
        pageDropdownText.setOnClickListener {
            val data = fullLayoutData ?: return@setOnClickListener
            val pages = data.optJSONArray("pages") ?: return@setOnClickListener
            if (pages.length() <= 1) return@setOnClickListener

            val pagesArray = mutableListOf<String>()
            for (i in 0 until pages.length()) {
                pagesArray.add(pages.getJSONObject(i).optString("name", "Page ${i + 1}"))
            }

            val listPopupWindow = android.widget.ListPopupWindow(this)
            val adapter = android.widget.ArrayAdapter(this, android.R.layout.simple_list_item_1, pagesArray)
            listPopupWindow.setAdapter(adapter)
            listPopupWindow.anchorView = it
            listPopupWindow.width = 800
            listPopupWindow.height = if (pages.length() > 6) 1000 else android.widget.ListPopupWindow.WRAP_CONTENT
            listPopupWindow.isModal = true
            
            listPopupWindow.setOnItemClickListener { _, _, position, _ ->
                if (System.currentTimeMillis() - lastMenuOpenTime < 500) return@setOnItemClickListener
                currentPageIndex = position
                displayCurrentPage()
                listPopupWindow.dismiss()
            }
            
            lastMenuOpenTime = System.currentTimeMillis()
            listPopupWindow.show()
        }

        if (lastIp.isNotEmpty()) {
            ipInput.setText(lastIp)
            connectBtn.text = "Connect"
        }

        connectBtn.setOnClickListener {
            val ip = ipInput.text.toString()
            if (ip.isEmpty()) return@setOnClickListener
            
            if (socket?.isConnected == true) {
                thread { output?.println("HELLO|$deviceId") }
                return@setOnClickListener
            }

            statusText.text = "Connecting..."
            pairingLayout.visibility = View.GONE
            
            thread {
                try {
                    val sslContext = SSLContext.getInstance("TLS")
                    sslContext.init(null, arrayOf<TrustManager>(object : X509TrustManager {
                        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
                    }), SecureRandom())

                    val factory = sslContext.socketFactory
                    socket = factory.createSocket(ip as String, 5000 as Int) as SSLSocket
                    output = PrintWriter(socket!!.getOutputStream(), true)
                    input = BufferedReader(InputStreamReader(socket!!.getInputStream()))
                    
                    prefs.edit().putString("last_ip", ip).apply()
                    runOnUiThread { 
                        connectBtn.text = "Refresh"
                        statusText.text = "Handshaking..."
                    }

                    val l_grid = buttonGrid
                    if (l_grid != null) {
                        output?.println("HELLO|$deviceId")
                        startListening(statusText, pairingLayout, connectBtn, pairingCodeInput)
                    }
                } catch (e: Exception) {
                    runOnUiThread { statusText.text = "Error: ${e.message}" }
                }
            }
        }

        statusText.setOnLongClickListener {
            // Restore functionality if needed, but IP is now always visible
            true
        }

        pairBtn.setOnClickListener {
            val code = pairingCodeInput.text.toString()
            thread { output?.println("PAIR|$deviceId|$code") }
        }

        checkForUpdates()
    }

    private fun checkForUpdates() {
        thread {
            try {
                // Version Check URL from update_locations.txt
                val versionUrl = "https://docs.google.com/document/d/1Ih0ncz6rIcAEEiyiQ9TQ4VQVINcnnL7A4zI4LlMbkUg/export?format=txt"
                val connection = java.net.URL(versionUrl).openConnection()
                connection.connectTimeout = 5000
                connection.readTimeout = 5000
                val content = connection.getInputStream().bufferedReader().use { it.readText() }
                
                val match = Regex("([\\d.]+)").find(content)
                val webVersion = match?.value ?: content.lines()[0].replace("v", "").trim()
                
                val currentVersion = "1.2" // This should ideally be BuildConfig.VERSION_NAME
                
                if (webVersion != currentVersion) {
                    runOnUiThread {
                        showUpdateDialog(webVersion)
                    }
                }
            } catch (e: Exception) {
                Log.e("TCD", "Update check failed: ${e.message}")
            }
        }
    }

    private fun showUpdateDialog(newVersion: String) {
        AlertDialog.Builder(this)
            .setTitle("Update Available")
            .setMessage("New version v$newVersion is available. Download and update now?")
            .setPositiveButton("Yes") { dialog, which ->
                val downloadUrl = "https://drive.google.com/file/d/1iKJkQe2x0EyWOW7T2gDqvPZOFFl5xCIK/view?usp=sharing"
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(downloadUrl)))
            }
            .setNegativeButton("No") { dialog, which ->
                finishAffinity()
            }
            .setCancelable(false)
            .show()
    }

    private fun startListening(statusText: TextView, pairingLayout: LinearLayout, connectBtn: Button, pairingCodeInput: EditText) {
        thread {
            try {
                while (true) {
                    val line = input?.readLine() ?: break
                    val displayLine = if (line.length > 100) line.substring(0, 100) + "..." else line
                    Log.d("TCD", "Received: $displayLine")
                    
                    if (line == "AUTH_REQUIRED") {
                        runOnUiThread { 
                            statusText.text = "Pairing Required"
                            pairingCodeInput.setText("")
                            pairingLayout.visibility = View.VISIBLE 
                        }
                    } else if (line == "AUTH_SUCCESS" || line == "PAIR_SUCCESS") {
                        runOnUiThread { 
                            statusText.text = "Connected"
                            pairingLayout.visibility = View.GONE
                            connectBtn.text = "Refresh"
                        }
                    } else if (line.startsWith("{")) {
                        try {
                            val json = JSONObject(line)
                            when (json.getString("type")) {
                                "LAYOUT" -> handleLayoutResponse(json.getJSONObject("data"))
                                "ASSET" -> handleAssetResponse(json)
                            }
                        } catch (e: Exception) {
                            Log.e("TCD", "JSON Parse Error: ${e.message}")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("TCD", "Socket Error: ${e.message}")
                try {
                    socket?.close()
                } catch (_: Exception) {}
                socket = null
                output = null
                input = null
                runOnUiThread { 
                    statusText.text = "Disconnected"
                    statusText.setTextColor(Color.parseColor("#ffb400"))
                    connectBtn.text = "Connect"
                }
            }
        }
    }

    private fun handleLayoutResponse(data: JSONObject) {
        fullLayoutData = data
        currentPageIndex = 0
        runOnUiThread { displayCurrentPage() }
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun displayCurrentPage() {
        val data = fullLayoutData ?: return
        val l_grid = buttonGrid ?: return

        runOnUiThread {
            try {
                val config = data.optJSONObject("config")
                val globalCols = config?.optInt("columns", 8) ?: 8
                val globalRows = config?.optInt("rows", 6) ?: 6
                val globalBgImage = config?.optString("background_image", "") ?: ""

                val pages = data.optJSONArray("pages")
                if (pages == null || pages.length() == 0) return@runOnUiThread

                val page = pages.getJSONObject(currentPageIndex)
                val pageName = page.optString("name", "Page ${currentPageIndex + 1}")
                val buttons = page.optJSONArray("buttons") ?: return@runOnUiThread
                var cols = page.optInt("columns", globalCols)
                var rows = page.optInt("rows", globalRows)
                val bgImage = page.optString("background_image", globalBgImage)

                findViewById<TextView>(R.id.pageDropdownText).text = if (pages.length() > 1) "$pageName ▼" else pageName
                findViewById<LinearLayout>(R.id.pageNavLayout).visibility = if (pages.length() > 0) View.VISIBLE else View.GONE

                val density = resources.displayMetrics.density
                val cellSizePx = (70 * density).toInt()

                for (i in 0 until buttons.length()) {
                    val b = buttons.getJSONObject(i)
                    val p = b.optJSONArray("position") ?: continue
                    val s = b.optJSONArray("size")
                    rows = maxOf(rows, p.getInt(0) + (s?.optInt(0, 1) ?: 1))
                    cols = maxOf(cols, p.getInt(1) + (s?.optInt(1, 1) ?: 1))
                }
                rows = maxOf(1, rows)
                cols = maxOf(1, cols)

                l_grid.removeAllViews()
                specialEmptyViews.clear()
                l_grid.columnCount = cols
                l_grid.rowCount = rows
                l_grid.useDefaultMargins = false
                l_grid.alignmentMode = GridLayout.ALIGN_BOUNDS

                buttonMap.clear()
                buttonDataMap.clear()
                val requestedInThisLayout = mutableSetOf<String>()
                val occupiedCells = mutableSetOf<String>()

                for (i in 0 until buttons.length()) {
                    val b = buttons.getJSONObject(i)
                    val pos = b.optJSONArray("position") ?: continue
                    val size = b.optJSONArray("size")
                    val rs = size?.optInt(0, 1) ?: 1
                    val cs = size?.optInt(1, 1) ?: 1
                    val r = pos.getInt(0)
                    val c = pos.getInt(1)
                    for (ri in 0 until rs) {
                        for (ci in 0 until cs) {
                            occupiedCells.add("${r + ri},${c + ci}")
                        }
                    }
                }

                val emptyFilename = "empty.png"
                if (!imageCache.containsKey(emptyFilename)) {
                    thread { output?.println("GET_ASSET|$emptyFilename") }
                }

                for (r in 0 until rows) {
                    for (c in 0 until cols) {
                        if (!occupiedCells.contains("$r,$c")) {
                            val emptyImg = android.widget.ImageView(this)
                            emptyImg.scaleType = android.widget.ImageView.ScaleType.FIT_XY
                            val params = GridLayout.LayoutParams(GridLayout.spec(r, 1), GridLayout.spec(c, 1))
                            params.width = cellSizePx
                            params.height = cellSizePx
                            emptyImg.layoutParams = params

                            if (imageCache.containsKey(emptyFilename)) {
                                val bitmap = imageCache[emptyFilename]
                                if (bitmap != null) {
                                    val drawable = BitmapDrawable(resources, bitmap)
                                    drawable.isFilterBitmap = true
                                    emptyImg.setImageDrawable(drawable)
                                }
                            } else {
                                val placeholderId = "EMPTY_${r}_${c}"
                                val list = pendingImages.getOrPut(emptyFilename) { mutableListOf() }
                                list.add(placeholderId)
                                specialEmptyViews[placeholderId] = emptyImg
                            }
                            l_grid.addView(emptyImg)
                        }
                    }
                }

                bgImageView?.setImageBitmap(null)
                bgImageView?.visibility = View.GONE

                backgroundFilename = if (bgImage.isNotEmpty()) bgImage.substringAfterLast("\\").substringAfterLast("/") else null
                backgroundFilename?.let { filename ->
                    if (imageCache.containsKey(filename)) {
                        bgImageView?.setImageBitmap(imageCache[filename])
                        bgImageView?.visibility = View.VISIBLE
                    } else {
                        thread { output?.println("GET_ASSET|$filename") }
                    }
                }

                for (i in 0 until buttons.length()) {
                    val bJson = buttons.getJSONObject(i)
                    val id = bJson.optString("id", "UNKNOWN_$i")
                    val pos = bJson.optJSONArray("position") ?: continue
                    val size = bJson.optJSONArray("size")
                    val rs = size?.optInt(0, 1) ?: 1
                    val cs = size?.optInt(1, 1) ?: 1
                    val r = pos.getInt(0)
                    val c = pos.getInt(1)

                    val frame = FrameLayout(this)
                    val params = GridLayout.LayoutParams(
                        GridLayout.spec(r, rs, GridLayout.FILL, 1f),
                        GridLayout.spec(c, cs, GridLayout.FILL, 1f)
                    )
                    params.width = cellSizePx * cs
                    params.height = cellSizePx * rs
                    params.setMargins(1, 1, 1, 1)
                    frame.layoutParams = params

                    val btnImg = ImageView(this)
                    btnImg.scaleType = ImageView.ScaleType.FIT_XY
                    val imgParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
                    btnImg.layoutParams = imgParams
                    val colorStr = bJson.optString("color", "#0f1f26")
                    try {
                        btnImg.setBackgroundColor(Color.parseColor(colorStr))
                    } catch (e: Exception) {
                        btnImg.setBackgroundColor(Color.parseColor("#0f1f26"))
                    }
                    frame.addView(btnImg)

                    val btnText = TextView(this)
                    btnText.text = bJson.optString("label", "")
                    btnText.setTextColor(Color.parseColor("#00f5ff"))
                    btnText.gravity = Gravity.CENTER
                    btnText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
                    btnText.setShadowLayer(2f, 1f, 1f, Color.BLACK)
                    val textParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
                    btnText.layoutParams = textParams
                    frame.addView(btnText)
                    btnText.bringToFront()

                    frame.setOnTouchListener { _, event ->
                        when (event.action) {
                            MotionEvent.ACTION_DOWN -> {
                                thread { output?.println("$id|PRESS") }
                                updateButtonVisual(id, true)
                            }
                            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                                thread { output?.println("$id|RELEASE") }
                                updateButtonVisual(id, false)
                            }
                        }
                        true
                    }

                    l_grid.addView(frame)
                    buttonMap[id] = frame
                    buttonDataMap[id] = bJson

                    listOf("image", "image_pressed").forEach { key ->
                        var path = bJson.optString(key, "")
                        if (path.isEmpty()) {
                            path = if (key == "image") "button.png" else "button_Press.png"
                        }

                        if (path.isNotEmpty()) {
                            val filename = path.substringAfterLast("\\").substringAfterLast("/")
                            if (imageCache.containsKey(filename)) {
                                updateButtonVisual(id, false)
                            } else {
                                val list = pendingImages.getOrPut(filename) { mutableListOf() }
                                if (!list.contains(id)) list.add(id)

                                if (!requestedInThisLayout.contains(filename)) {
                                    requestedInThisLayout.add(filename)
                                    thread { output?.println("GET_ASSET|$filename") }
                                }
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("TCD", "Error in layout: ${e.message}")
            }
        }
    }

    private fun updateButtonVisual(id: String, pressed: Boolean) {
        val container = buttonMap[id] as? FrameLayout ?: return
        val data = buttonDataMap[id] ?: return
        val imageView = container.getChildAt(0) as? ImageView ?: return
        val textView = container.getChildAt(1) as? TextView ?: return
        
        runOnUiThread {
            var imgPath = data.optString(if (pressed) "image_pressed" else "image", "")
            if (imgPath.isEmpty()) {
                // Default fallback if no image specified
                imgPath = if (pressed) "button_Press.png" else "button.png"
            }
            
            val filename = imgPath.substringAfterLast("\\").substringAfterLast("/")
            val bitmap = imageCache[filename]
            
            textView.setTextColor(Color.parseColor("#00f5ff"))
            textView.text = data.optString("label", "")

            if (bitmap != null) {
                val drawable = BitmapDrawable(resources, bitmap)
                drawable.isFilterBitmap = true
                imageView.setImageDrawable(drawable)
                imageView.setBackgroundColor(Color.TRANSPARENT)
            } else {
                val scAmber = Color.parseColor("#ffb400")
                imageView.setImageDrawable(null)
                imageView.setBackgroundColor(if (pressed) scAmber else Color.parseColor(data.optString("color", "#0f1f26")))
            }
        }
    }

    private fun handleAssetResponse(json: JSONObject) {
        val filename = json.getString("filename")
        val dataStr = json.getString("data")
        
        try {
            val bytes = Base64.decode(dataStr, Base64.DEFAULT)
            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            if (bitmap != null) {
                imageCache[filename] = bitmap
                runOnUiThread {
                    if (filename == backgroundFilename) {
                        bgImageView?.setImageBitmap(bitmap)
                        bgImageView?.visibility = View.VISIBLE
                    }
                    pendingImages[filename]?.forEach { id -> 
                        if (id.startsWith("EMPTY_")) {
                            specialEmptyViews[id]?.setImageBitmap(bitmap)
                        } else {
                            updateButtonVisual(id, false)
                        }
                    }
                    pendingImages.remove(filename)
                }
            }
        } catch (e: Exception) {
            Log.e("TCD", "Error processing asset $filename: ${e.message}")
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        thread { socket?.close() }
    }
}
